//! PyO3 bridge — the seam between Rust and Python. treat with respect.

#![allow(clippy::useless_conversion)]

use pyo3::prelude::*;

/// the event bus, as seen from Python.
#[pyclass]
pub struct EventBus;

#[pymethods]
#[allow(clippy::useless_conversion)]
impl EventBus {
    #[new]
    pub fn new() -> Self {
        Self
    }

    /// publish an event to a topic.
    pub fn publish(&self, _event: Event) -> PyResult<()> {
        // todo: wire to bus transport
        Ok(())
    }

    /// subscribe to a topic.
    pub fn subscribe(&self, _topic: &str) -> PyResult<()> {
        // todo: wire to bus transport
        Ok(())
    }
}

impl Default for EventBus {
    fn default() -> Self {
        Self::new()
    }
}

/// a single event flowing through the bus.
#[pyclass]
#[derive(Clone)]
pub struct Event {
    #[pyo3(get, set)]
    pub topic:   String,
    #[pyo3(get, set)]
    pub payload: String,
}

#[pymethods]
#[allow(clippy::useless_conversion)]
impl Event {
    #[new]
    pub fn new(topic: String, payload: String) -> Self {
        Self { topic, payload }
    }

    pub fn __repr__(&self) -> String {
        format!("Event(topic={:?}, payload={:?})", self.topic, self.payload)
    }
}