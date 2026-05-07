import argparse
import json
from pathlib import Path

import pyautogui
from PIL import ImageDraw

from telegram_ads_auto import INPUT_FILE, campaign_targets, load_campaigns
from telegram_ads_screen_auto import (
    bot_line_matches,
    check_stop,
    clear_draft,
    focus_target_bots_input,
    go_to_account_page,
    load_used_target_keys,
    low_file_for_input,
    paste_channel_from_clipboard,
    remember_low_bot,
    sleep_checked,
    sleep_real,
    start_emergency_stop_listener,
    target_bot_daily_users_error_visible,
    target_key,
    unique_targets,
)


CHECK_CONFIG_FILE = Path(__file__).with_name("bot_check_coords.json")
COORDS_SCREENSHOT_FILE = Path(__file__).with_name("checker_coords_layout.png")


def wait_user_point(name: str) -> dict:
    input(f"Наведи мышь на '{name}' и нажми Enter в консоли...")
    x, y = pyautogui.position()
    print(f"{name}: x={x}, y={y}")
    return {"x": x, "y": y}


def wait_user_region(name: str) -> dict:
    print(f"{name}: сначала наведи мышь на левый верхний угол области и нажми Enter.")
    top_left = wait_user_point(f"{name} top-left")
    print(f"{name}: теперь наведи мышь на правый нижний угол области и нажми Enter.")
    bottom_right = wait_user_point(f"{name} bottom-right")
    return {
        "x": min(top_left["x"], bottom_right["x"]),
        "y": min(top_left["y"], bottom_right["y"]),
        "width": abs(bottom_right["x"] - top_left["x"]),
        "height": abs(bottom_right["y"] - top_left["y"]),
    }


def calibrate_checker() -> None:
    print("Открой Telegram Ads на форме New Ad. Эти координаты только для проверки ботов.")
    config = {
        "create_new_ad": wait_user_point("Create a new ad"),
        "bots_tab": wait_user_point("Target Bots tab"),
        "target_channels_label": wait_user_point("Target specific bots label/area"),
        "clear_draft": wait_user_point("Clear Draft"),
        "address_bar": wait_user_point("Browser address bar"),
        "target_bot_error_region": wait_user_region("Target bot 1000+ error region"),
    }
    CHECK_CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved checker coordinates to {CHECK_CONFIG_FILE}")


def load_check_config() -> dict:
    if not CHECK_CONFIG_FILE.exists():
        raise SystemExit(
            "Нет bot_check_coords.json. Сначала запусти: python telegram_bot_checker.py --calibrate"
        )
    return json.loads(CHECK_CONFIG_FILE.read_text(encoding="utf-8"))


def save_coords_screenshot() -> None:
    image = pyautogui.screenshot()
    draw = ImageDraw.Draw(image)

    if CHECK_CONFIG_FILE.exists():
        config = load_check_config()
        for name, value in config.items():
            if {"x", "y", "width", "height"}.issubset(value):
                x1 = value["x"]
                y1 = value["y"]
                x2 = x1 + value["width"]
                y2 = y1 + value["height"]
                draw.rectangle((x1, y1, x2, y2), outline="red", width=4)
                draw.text((x1 + 6, y1 + 6), name, fill="red")
                continue

            x = value["x"]
            y = value["y"]
            draw.ellipse((x - 10, y - 10, x + 10, y + 10), outline="red", width=4)
            draw.line((x - 16, y, x + 16, y), fill="red", width=3)
            draw.line((x, y - 16, x, y + 16), fill="red", width=3)
            draw.text((x + 14, y + 4), name, fill="red")
    else:
        draw.text((20, 20), "bot_check_coords.json not calibrated yet", fill="red")

    image.save(COORDS_SCREENSHOT_FILE)
    print(f"Saved checker coordinate screenshot: {COORDS_SCREENSHOT_FILE}")


def read_target_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            keys.add(target_key(line.rsplit("\t", 1)[-1]))
    return keys


def bot_exists_in_file(path: Path, bot: str) -> bool:
    if not path.exists():
        return False
    return any(bot_line_matches(line.strip(), bot) for line in path.read_text(encoding="utf-8").splitlines())


def load_candidate_bots(input_path: Path, start_block: int, limit: int = 0) -> list[str]:
    campaigns = load_campaigns(input_path, 1, False, start_block)
    bots = []
    for campaign in campaigns:
        bots.extend(campaign_targets(campaign))

    excluded = set()
    excluded.update(load_used_target_keys())
    excluded.update(read_target_keys(low_file_for_input(input_path)))

    result = []
    for bot in unique_targets(bots):
        if target_key(bot) in excluded:
            continue
        result.append(bot)
        if limit and len(result) >= limit:
            break
    return result


def open_new_ad_for_check(config: dict, skip_create_click: bool = False) -> None:
    check_stop()
    if not skip_create_click:
        pyautogui.click(config["create_new_ad"]["x"], config["create_new_ad"]["y"])
        sleep_checked(0.8)
    pyautogui.click(config["bots_tab"]["x"], config["bots_tab"]["y"])
    sleep_checked(0.3)


def reset_check_form(config: dict) -> None:
    clear_draft(config)
    go_to_account_page(config)


def reset_failed_check_form(config: dict) -> None:
    clear_draft(config)
    go_to_account_page(config)


def save_checker_screenshots(config: dict, bot: str) -> None:
    pyautogui.screenshot().save(Path(__file__).with_name("checker_before_add.png"))
    focus_target_bots_input(config)
    paste_channel_from_clipboard(bot)
    sleep_real(0.7)
    pyautogui.screenshot().save(Path(__file__).with_name("checker_after_add.png"))
    print("Saved checker_before_add.png and checker_after_add.png")


def count_red_pixels(region: dict) -> int:
    image = pyautogui.screenshot(
        region=(region["x"], region["y"], region["width"], region["height"])
    )
    red_pixels = 0
    for r, g, b in image.convert("RGB").getdata():
        if r > 180 and g < 110 and b < 110:
            red_pixels += 1
    return red_pixels


def check_one_bot(config: dict, bot: str, input_path: Path) -> bool:
    region = config.get("target_bot_error_region")
    before_red = count_red_pixels(region) if region else 0
    focus_target_bots_input(config)
    paste_channel_from_clipboard(bot)
    sleep_real(0.7)
    after_red = count_red_pixels(region) if region else 0
    if target_bot_daily_users_error_visible(config) and after_red > before_red + 250:
        remember_low_bot({"title": "checker", "block_number": "check"}, bot, input_path)
        print(f"LOW: {bot} (red pixels {before_red} -> {after_red})")
        return False
    print(f"OK: {bot} (red pixels {before_red} -> {after_red})")
    return True


def run_checker(args: argparse.Namespace) -> None:
    start_emergency_stop_listener()
    config = load_check_config()
    bots = load_candidate_bots(args.input, args.start_block, args.limit)
    if not bots:
        print("Нет ботов для проверки после фильтра used/low/checked.")
        return

    low_file = low_file_for_input(args.input)
    print(f"Will check {len(bots)} target(s). OK targets stay in {args.input}. Low: {low_file}.")
    first = True
    for bot in bots:
        check_stop()
        open_new_ad_for_check(config, skip_create_click=args.skip_create_click and first)
        first = False
        if args.screens:
            save_checker_screenshots(config, bot)
            reset_check_form(config)
        else:
            ok = check_one_bot(config, bot, args.input)
            if ok:
                reset_check_form(config)
            else:
                reset_failed_check_form(config)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--input", type=Path, default=INPUT_FILE)
    parser.add_argument("--start-block", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--screens", action="store_true", help="Save before/after screenshots for the first checked bots.")
    parser.add_argument("--coords-screenshot", action="store_true", help="Save screenshot with checker coordinates.")
    parser.add_argument("--skip-create-click", action="store_true", help="Use if New Ad form is already open.")
    args = parser.parse_args()

    if args.calibrate:
        calibrate_checker()
        return

    if args.coords_screenshot:
        save_coords_screenshot()
        return

    run_checker(args)


if __name__ == "__main__":
    main()
