// pydwshape._pydwshape — native PyO3 (abi3) binding over the dwtshape engine.
//
// Windows-only by design: the engine loads + hooks DWriteCore. On non-Windows
// this crate would not even compile (dwtshape depends on the `windows` crate).
//
// The Python wrapper in `pydwshape/__init__.py` passes the bundled
// DWriteCore.dll path explicitly; callers get the babelsoft
// `/api/opentype/shape` dict via `pydwshape.shape_with_dwrite(...)`.

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::PathBuf;

/// Shape `text` with the font bytes `data` and return the babelsoft engine
/// JSON string (same schema as the `dwtshape` CLI stdout).
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
    // Write the font to a temp file (the engine shapes from a file path).
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

    // Engine internals panic on hard failures; never let a panic unwind across
    // the FFI boundary into Python.
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
    // Unique per (pid, counter) so concurrent calls in one process don't clash.
    use std::sync::atomic::{AtomicU64, Ordering};
    static N: AtomicU64 = AtomicU64::new(0);
    let n = N.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!("dwtshape_{}_{}.font", std::process::id(), n))
}

#[pymodule]
fn _pydwshape(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(shape_json, m)?)?;
    Ok(())
}
