// pydwshape._pydwshape — native PyO3 (abi3) binding over the dwtshape
// (DWriteCore) engine.
//
// Windows-only: the engine loads + hooks DWriteCore (bundled in the wheel).
// On non-Windows this module still compiles (the dwtshape dependency is
// target-gated in Cargo.toml) but the dwcore backend raises; use the
// cross-platform Wine DWrite backend (`pydwshape.shape_with_dwrite(..., backend=
// "winedwrite")`, ctypes over the bundled wine port shared library).

use pyo3::prelude::*;

#[cfg(windows)]
mod imp {
    use pyo3::exceptions::PyRuntimeError;
    use pyo3::prelude::*;
    use std::panic::{catch_unwind, AssertUnwindSafe};
    use std::path::PathBuf;

    pub fn shape_json(
        py: Python<'_>,
        data: &[u8],
        text: &str,
        script: &str,
        language: &str,
        direction: &str,
        show_all_lookups: bool,
        features: Option<String>,
        dwcore: Option<String>,
    ) -> PyResult<String> {
        let tmp = temp_font_path();
        std::fs::write(&tmp, data).map_err(|e| PyRuntimeError::new_err(format!("write font: {e}")))?;

        let opts = dwtshape::ShapeOpts {
            font: tmp.to_string_lossy().into_owned(),
            text: text.to_owned(),
            script: script.to_owned(),
            language: language.to_owned(),
            direction: direction.to_owned(),
            show_all: show_all_lookups,
            dwcore,
            features_arg: features.unwrap_or_default(),
        };

        let result = py.allow_threads(|| {
            let r = catch_unwind(AssertUnwindSafe(|| dwtshape::shape_json(opts)));
            let _ = std::fs::remove_file(&tmp);
            r
        });

        match result {
            Ok(Ok(json)) => Ok(json),
            Ok(Err(e)) => Err(PyRuntimeError::new_err(e)),
            Err(_) => Err(PyRuntimeError::new_err(
                "dwtshape engine panicked (unsupported DWriteCore build? see README)",
            )),
        }
    }

    fn temp_font_path() -> PathBuf {
        use std::sync::atomic::{AtomicU64, Ordering};
        static N: AtomicU64 = AtomicU64::new(0);
        let n = N.fetch_add(1, Ordering::Relaxed);
        std::env::temp_dir().join(format!("dwtshape_{}_{}.font", std::process::id(), n))
    }
}

#[cfg(not(windows))]
mod imp {
    use pyo3::exceptions::PyRuntimeError;
    use pyo3::prelude::*;

    pub fn shape_json(
        _py: Python<'_>,
        _data: &[u8],
        _text: &str,
        _script: &str,
        _language: &str,
        _direction: &str,
        _show_all_lookups: bool,
        _features: Option<String>,
        _dwcore: Option<String>,
    ) -> PyResult<String> {
        Err(PyRuntimeError::new_err(
            "backend 'dwcore' requires a Windows build (bundled Microsoft DWriteCore). Use backend='winedwrite' (the bundled Wine DWrite port) on this platform.",
        ))
    }
}

/// Shape `text` with the font bytes `data` and return the babelsoft engine
/// JSON string (dwcore / native DWriteCore backend; Windows only).
#[pyfunction]
#[pyo3(
    signature = (data, text, *, script = "", language = "", direction = "auto",
                show_all_lookups = false, features = None, dwcore = None)
)]
fn shape_json(
    py: Python<'_>,
    data: &[u8],
    text: &str,
    script: &str,
    language: &str,
    direction: &str,
    show_all_lookups: bool,
    features: Option<String>,
    dwcore: Option<String>,
) -> PyResult<String> {
    imp::shape_json(py, data, text, script, language, direction,
                    show_all_lookups, features, dwcore)
}

#[pymodule]
fn _pydwshape(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(shape_json, m)?)?;
    Ok(())
}
