IMAGEGEN_PREFIX = "$imagegen"
ASPECT_RATIO_NONE = "none"
ALLOWED_ASPECT_RATIOS = (ASPECT_RATIO_NONE, "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3")


def build_imagegen_prompt(user_prompt: str, aspect_ratio: str = ASPECT_RATIO_NONE) -> str:
    prompt = (user_prompt or "").strip()
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        raise ValueError(f"Unsupported aspect_ratio: {aspect_ratio}")
    if prompt.startswith(IMAGEGEN_PREFIX):
        return prompt

    if aspect_ratio != ASPECT_RATIO_NONE:
        prompt = f"画面比例 {aspect_ratio}。{prompt}"
    return f"{IMAGEGEN_PREFIX} {prompt}"
