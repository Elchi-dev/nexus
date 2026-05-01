//! PyO3 bridge — the seam between Rust and Python. treat with respect.

use pyo3::prelude::*;

#[pyclass]
pub struct EventBus;

#[pymethods]
impl EventBus {
    #[new]
    pub fn new() -> Self { Self }

    pub fn publish(&self, event: Event) -> PyResult<()> {
        let _ = event;
        Ok(())
    }

    pub fn subscribe(&self, topic: &str) -> PyResult<()> {
        let _ = topic;
        Ok(())
    }
}

#[pyclass]
#[derive(Clone)]
pub struct Event {
    #[pyo3(get, set)] pub topic:   String,
    #[pyo3(get, set)] pub payload: String,
}

#[pymethods]
impl Event {
    #[new]
    pub fn new(topic: String, payload: String) -> Self {
        Self { topic, payload }
    }

    pub fn __repr__(&self) -> String {
        format!("Event(topic={:?}, payload={:?})", self.topic, self.payload)
    }
}
