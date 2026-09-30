CREATE INDEX IF NOT EXISTS idx_network_edges_from_node ON network_edges(from_node_id);
CREATE INDEX IF NOT EXISTS idx_network_edges_to_node ON network_edges(to_node_id);
