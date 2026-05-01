//! internal event bus — pub/sub routing and queue management.

#[derive(Debug, Clone)]
pub enum Transport {
    UnixSocket(String),
    Tcp(String),
}

#[derive(Debug, Clone)]
pub struct BusConfig {
    pub max_queue_size: usize,
    pub transport: Transport,
}

impl Default for BusConfig {
    fn default() -> Self {
        Self {
            max_queue_size: 10_000,
            transport: Transport::UnixSocket("/tmp/nexus.sock".into()),
        }
    }
}
