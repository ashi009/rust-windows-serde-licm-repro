#[inline(never)]
pub fn parse_str(input: &str) -> Result<boundary_model::Wide, serde_json::Error> {
    boundary_model::parse_str(input)
}

#[inline(never)]
pub fn parse_slice(input: &[u8]) -> Result<boundary_model::Wide, serde_json::Error> {
    boundary_model::parse_slice(input)
}
