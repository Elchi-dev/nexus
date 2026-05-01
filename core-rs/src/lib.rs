//! nexus-core-rs — the Rust event bus that powers nexus.
//!
//! exposed to Python via PyO3. if you are reading this wondering why
//! a Discord bot orchestrator has a Rust event bus, welcome.
//! please see the README. we do not apologise.

use pyo3::prelude::*;

mod bridge;
mod bus;

#[pymodule]
fn nexus_core_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<bridge::EventBus>()?;
    m.add_class::<bridge::Event>()?;
    Ok(())
}
