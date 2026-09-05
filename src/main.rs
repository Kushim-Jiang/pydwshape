// dwtshape CLI — thin wrapper over the dwtshape library engine.
fn main() {
    let argv: Vec<String> = std::env::args().collect();
    std::process::exit(dwtshape::run_cli(&argv));
}
