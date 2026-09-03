#[inline(never)]
pub fn parse_str(input: &str) -> Result<model_only::Wide, serde_json::Error> {
    serde_json::from_str(input)
}

#[inline(never)]
pub fn parse_slice(input: &[u8]) -> Result<model_only::Wide, serde_json::Error> {
    serde_json::from_slice(input)
}
