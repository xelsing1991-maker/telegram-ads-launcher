import argparse
import ctypes
import ctypes.wintypes
import json
import threading
import time
from pathlib import Path

import pyautogui
import pyperclip
from pywinauto.keyboard import send_keys
from pynput.keyboard import Controller, Key
from pynput.keyboard import Listener

from telegram_ads_auto import AD_TEXTS, DATA_DIR, INPUT_FILE, PROMOTE_URL, campaign_number, campaign_targets, load_campaigns, normalize_cpm, source_name, source_title_prefix


CONFIG_FILE = Path(__file__).with_name("screen_coords.json")
LOW_BOTS_FILE = DATA_DIR / "low-bots.txt"
LOW_CHANNEL_FILE = DATA_DIR / "low-channel.txt"
USED_BOTS_FILE = DATA_DIR / "used-bots.txt"
USED_CHANNEL_FILE = DATA_DIR / "used-channel.txt"
PENDING_BOTS_FILE = DATA_DIR / "pending-bots.txt"
PENDING_CHANNEL_FILE = DATA_DIR / "pending-channel.txt"
MIN_ACCEPTED_TARGETS = 3
MAX_RETRY_ATTEMPTS = 100

SPEED = 2.0
pyautogui.PAUSE = 0.04
keyboard = Controller()
stop_event = threading.Event()

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
sendinput_user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.OpenClipboard.argtypes = [ctypes.c_void_p]
user32.OpenClipboard.restype = ctypes.c_bool
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = ctypes.c_bool
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [ctypes.c_uint]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = ctypes.c_bool
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = ctypes.c_bool
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.restype = ctypes.c_void_p

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_A = 0x41
VK_C = 0x43
VK_L = 0x4C
VK_V = 0x56
VK_INSERT = 0x2D
VK_BACKSPACE = 0x08
VK_DELETE = 0x2E


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]


sendinput_user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
sendinput_user32.SendInput.restype = ctypes.c_uint
user32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.restype = ctypes.c_bool


def on_key_press(key) -> None:
    if key == Key.f4:
        stop_event.set()
        print("Emergency stop requested with F4.")


def start_emergency_stop_listener() -> Listener:
    listener = Listener(on_press=on_key_press)
    listener.daemon = True
    listener.start()
    return listener


def check_stop() -> None:
    if stop_event.is_set():
        raise SystemExit("Stopped by F4.")


def sleep_checked(seconds: float) -> None:
    seconds = max(seconds / SPEED, 0.02)
    end_time = time.time() + seconds
    while time.time() < end_time:
        check_stop()
        time.sleep(min(0.05, end_time - time.time()))


def sleep_fast(seconds: float) -> None:
    time.sleep(max(seconds / SPEED, 0.02))


def sleep_real(seconds: float) -> None:
    end_time = time.time() + seconds
    while time.time() < end_time:
        check_stop()
        time.sleep(min(0.1, end_time - time.time()))


def set_clipboard_text(text: str) -> None:
    # Use the native Windows clipboard API so Cyrillic text is stored as
    # CF_UNICODETEXT without depending on PowerShell or terminal encoding.
    if not user32.OpenClipboard(None):
        raise RuntimeError("Could not open Windows clipboard.")
    try:
        user32.EmptyClipboard()
        data = (text + "\0").encode("utf-16-le")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
        if not handle:
            raise RuntimeError("Could not allocate clipboard memory.")

        locked = kernel32.GlobalLock(handle)
        if not locked:
            kernel32.GlobalFree(handle)
            raise RuntimeError("Could not lock clipboard memory.")

        try:
            ctypes.memmove(locked, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)

        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise RuntimeError("Could not set Windows clipboard data.")
    finally:
        user32.CloseClipboard()


def get_clipboard_text() -> str:
    if not user32.OpenClipboard(None):
        raise RuntimeError("Could not open Windows clipboard.")
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        locked = kernel32.GlobalLock(handle)
        if not locked:
            return ""
        try:
            return ctypes.wstring_at(locked)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def hotkey(*keys: str) -> None:
    for key in keys:
        pyautogui.keyDown(key)
    sleep_fast(0.02)
    for key in reversed(keys):
        pyautogui.keyUp(key)
    sleep_fast(0.03)


def send_input_chord(*vks: int) -> None:
    events = []
    for vk in vks:
        events.append(INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(vk, 0, 0, 0, None))))
    for vk in reversed(vks):
        events.append(
            INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, None)))
        )
    event_array = (INPUT * len(events))(*events)
    sendinput_user32.SendInput(len(events), event_array, ctypes.sizeof(INPUT))
    sleep_fast(0.06)


def focus_point(point: dict) -> None:
    pyautogui.click(point["x"], point["y"])
    sleep_fast(0.07)
    screen_point = ctypes.wintypes.POINT(point["x"], point["y"])
    hwnd = user32.WindowFromPoint(screen_point)
    if hwnd:
        user32.SetForegroundWindow(hwnd)
        sleep_fast(0.07)


def paste_hotkey_auto() -> None:
    hotkey("ctrl", "v")
    sleep_fast(0.08)
    send_keys("^v", pause=0.05, vk_packet=False)
    sleep_fast(0.08)
    send_input_chord(VK_CONTROL, VK_V)
    send_input_chord(VK_SHIFT, VK_INSERT)


def clear_field_auto() -> None:
    hotkey("ctrl", "a")
    pyautogui.press("backspace")
    sleep_fast(0.05)
    send_keys("^a{BACKSPACE}", pause=0.05, vk_packet=False)
    sleep_fast(0.05)
    send_input_chord(VK_CONTROL, VK_A)
    send_input_chord(VK_BACKSPACE)


def paste_text(text: str) -> None:
    set_clipboard_text(text)
    hotkey("ctrl", "a")
    pyautogui.press("backspace")
    sleep_fast(0.03)
    hotkey("ctrl", "v")
    sleep_fast(0.12)


def clear_current_field() -> None:
    hotkey("ctrl", "a")
    pyautogui.press("backspace")
    sleep_fast(0.03)


def context_paste_current_field(text: str) -> None:
    set_clipboard_text(text)
    pyautogui.rightClick()
    sleep_fast(0.08)
    # Edge Russian context menu: "Вставить" is the first enabled paste item at this offset.
    pyautogui.moveRel(75, 185)
    pyautogui.click()
    sleep_fast(0.12)


def paste_via_context_menu(text: str, point: dict | None = None) -> None:
    set_clipboard_text(text)
    if point is None:
        pyautogui.rightClick()
    else:
        pyautogui.rightClick(point["x"], point["y"])
    sleep_fast(0.08)
    pyautogui.moveRel(75, 185)
    pyautogui.click()
    sleep_fast(0.15)


def paste_via_windows_context_menu(text: str, point: dict | None = None, clear: bool = True) -> None:
    set_clipboard_text(text)
    if point is not None:
        focus_point(point)
    if clear:
        clear_field_auto()
    if point is None:
        pyautogui.rightClick()
    else:
        pyautogui.rightClick(point["x"], point["y"])
    sleep_fast(0.12)
    # Russian Edge/Windows context menu: "Вставить" is usually at this offset.
    pyautogui.moveRel(75, 185)
    pyautogui.click()
    sleep_fast(0.18)


def paste_via_shift_insert(text: str, point: dict | None = None, clear: bool = True) -> None:
    check_stop()
    set_clipboard_text(text)
    if point is not None:
        focus_point(point)
    if clear:
        clear_field_auto()
    shift_insert_channel_paste()
    sleep_checked(0.12)


def paste_channel_from_clipboard(channel: str) -> None:
    check_stop()
    set_clipboard_text(channel)
    shift_insert_channel_paste()
    check_stop()
    pyautogui.press("enter")
    sleep_checked(0.3)


def shift_insert_channel_paste() -> None:
    # Channel-only wrapper. Use one Shift+Insert path to avoid duplicate pastes.
    with keyboard.pressed(Key.shift):
        keyboard.press(Key.insert)
        sleep_checked(0.03)
        keyboard.release(Key.insert)
    sleep_checked(0.12)


def has_blue_checkmark(point: dict) -> bool:
    image = pyautogui.screenshot(region=(point["x"] - 8, point["y"] - 8, 24, 24))
    blue_pixels = 0
    for r, g, b in image.convert("RGB").getdata():
        if r < 90 and g > 100 and b > 150:
            blue_pixels += 1
    return blue_pixels >= 8


def has_red_error_region(region: dict) -> bool:
    image = pyautogui.screenshot(
        region=(region["x"], region["y"], region["width"], region["height"])
    )
    red_pixels = 0
    for r, g, b in image.convert("RGB").getdata():
        if r > 180 and g < 110 and b < 110:
            red_pixels += 1
    return red_pixels >= 700


def target_bot_daily_users_error_visible(config: dict) -> bool:
    region = config.get("target_bot_error_region")
    if not region:
        return False
    return has_red_error_region(region)


def ensure_checkbox_checked(config: dict, name: str) -> None:
    check_stop()
    point = config[name]
    if has_blue_checkmark(point):
        return
    for _ in range(3):
        click_point(config, name)
        sleep_checked(0.3)
        if has_blue_checkmark(point):
            return
    print(f"Warning: {name} checkbox still does not look checked.")


def ensure_blue_option_selected(config: dict, name: str) -> None:
    check_stop()
    point = config[name]
    if has_blue_checkmark(point):
        return
    offsets = [(0, 0), (-6, 0), (6, 0), (0, -6), (0, 6)]
    for dx, dy in offsets:
        pyautogui.click(point["x"] + dx, point["y"] + dy)
        sleep_checked(0.3)
        if has_blue_checkmark(point):
            return
    print(f"Warning: {name} option still does not look selected.")


def copy_selected_field_text() -> str:
    pyperclip.copy("")
    hotkey("ctrl", "a")
    time.sleep(0.03)
    hotkey("ctrl", "c")
    time.sleep(0.07)
    return pyperclip.paste()


def paste_text_strict(text: str, field_name: str, retries: int = 3) -> None:
    for attempt in range(1, retries + 1):
        clear_current_field()
        context_paste_current_field(text)
        actual = copy_selected_field_text()
        if actual == text:
            return

        print(f"Retry {attempt}/{retries}: {field_name} mismatch. Expected {text!r}, got {actual!r}")
        sleep_fast(0.13)

    screenshot = Path(__file__).with_name(f"strict_error_{field_name}.png")
    pyautogui.screenshot().save(screenshot)
    raise RuntimeError(
        f"Strict check failed for {field_name}. "
        f"Screenshot saved: {screenshot}. The ad was not submitted."
    )


def paste_text_best_effort(text: str) -> None:
    pyperclip.copy(text)
    with keyboard.pressed(Key.ctrl):
        keyboard.press("a")
        keyboard.release("a")
    sleep_fast(0.03)
    with keyboard.pressed(Key.ctrl):
        keyboard.press("v")
        keyboard.release("v")
    sleep_fast(0.07)


def fill_field(config: dict, point_name: str, value: str, strict: bool) -> None:
    click_point(config, point_name)
    if strict:
        paste_text_strict(value, point_name)
    else:
        paste_text_best_effort(value)


def fill_current_field(value: str, field_name: str, strict: bool) -> None:
    if strict:
        paste_text_strict(value, field_name)
    else:
        paste_text(value)


def tab_to_next_field() -> None:
    pyautogui.press("tab")
    sleep_fast(0.08)


def fill_after_label(config: dict, label_name: str, field_name: str, value: str) -> None:
    check_stop()
    if field_name in config:
        focus_point(config[field_name])
        sleep_checked(0.07)
    else:
        click_point(config, label_name)
        sleep_checked(0.05)
        pyautogui.press("tab")
        sleep_checked(0.07)
    paste_via_shift_insert(value, config[field_name])


def click_point(config: dict, name: str) -> None:
    point = config[name]
    pyautogui.click(point["x"], point["y"])


def click_optional_point(config: dict, *names: str) -> bool:
    for name in names:
        if name in config:
            click_point(config, name)
            return True
    return False


def reset_form_scroll() -> None:
    check_stop()
    pyautogui.press("home")
    sleep_checked(0.25)


def refresh_page_after_create() -> None:
    check_stop()
    pyautogui.press("f5")
    sleep_checked(1.6)


def clear_draft(config: dict) -> None:
    check_stop()
    if "clear_draft" in config:
        click_point(config, "clear_draft")
        sleep_real(1.0)
    else:
        pyautogui.press("f5")
        sleep_real(1.0)


def go_to_account_page(config: dict) -> None:
    check_stop()
    account_url = "https://ads.telegram.org/account/"
    set_clipboard_text(account_url)
    pyperclip.copy(account_url)
    sleep_real(0.3)
    if "address_bar" in config:
        focus_point(config["address_bar"])
    sleep_real(0.12)
    send_keys("%d", pause=0.05, vk_packet=False)
    sleep_real(0.08)
    send_input_chord(VK_CONTROL, VK_L)
    sleep_real(0.08)
    send_input_chord(VK_CONTROL, VK_A)
    sleep_real(0.08)
    set_clipboard_text(account_url)
    pyperclip.copy(account_url)
    send_input_chord(VK_CONTROL, VK_V)
    sleep_real(0.1)
    pyautogui.press("enter")
    sleep_real(2.0)


def reset_after_rejected_bot(config: dict) -> None:
    print("Clearing rejected draft...")
    clear_draft(config)
    print("Returning to Telegram Ads account page...")
    go_to_account_page(config)


def focus_target_bots_input(config: dict) -> None:
    check_stop()
    point = config.get("target_channels_label") or config.get("target_channels")
    if point:
        pyautogui.click(point["x"], point["y"] + 1)
        sleep_checked(0.05)
        pyautogui.press("tab")
        sleep_checked(0.07)
        return

    raise KeyError("No target channels coordinates configured")


def clear_rejected_target_input(config: dict) -> None:
    check_stop()
    focus_target_bots_input(config)
    sleep_real(0.12)
    pyautogui.press("esc")
    sleep_real(0.12)
    focus_target_bots_input(config)
    sleep_real(0.12)
    hotkey("ctrl", "a")
    sleep_real(0.12)
    send_input_chord(VK_CONTROL, VK_A)
    sleep_real(0.12)
    pyautogui.press("backspace")
    sleep_real(0.12)
    pyautogui.press("delete")
    send_input_chord(VK_DELETE)
    sleep_real(0.2)


def undo_rejected_target(config: dict) -> None:
    clear_rejected_target_input(config)
    sleep_real(0.4)
    if target_bot_daily_users_error_visible(config):
        clear_rejected_target_input(config)


def target_key(value: str) -> str:
    value = value.strip().lstrip("@")
    value = value.removeprefix("https://").removeprefix("http://")
    value = value.removeprefix("t.me/")
    return value.rstrip("/").lower()


def bot_line_matches(line: str, bot: str) -> bool:
    return target_key(line) == target_key(bot)


def remove_bot_from_input_file(input_path: Path, bot: str) -> bool:
    if not input_path.exists():
        return False

    lines = input_path.read_text(encoding="utf-8").splitlines()
    removed = False
    kept_lines = []
    for line in lines:
        if not removed and bot_line_matches(line, bot):
            removed = True
            continue
        kept_lines.append(line)

    if removed:
        input_path.write_text("\n".join(kept_lines).rstrip() + "\n", encoding="utf-8")
    return removed


def remember_low_bot(campaign: dict, bot: str, input_path: Path) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    low_file = low_file_for_input(input_path)
    block = campaign.get("block_number", "?")
    line = f"{campaign['title']}\tblock {block}\t{bot}\n"
    existing = low_file.read_text(encoding="utf-8").splitlines() if low_file.exists() else []
    existing_low_keys = {target_key(existing_line.rsplit("\t", 1)[-1]) for existing_line in existing}
    if target_key(bot) not in existing_low_keys:
        with low_file.open("a", encoding="utf-8") as file:
            file.write(line)
    if remove_bot_from_input_file(input_path, bot):
        print(f"Removed low target from {input_path.name}: {bot}")
    else:
        print(f"Warning: low target was not found in {input_path.name}: {bot}")


def unique_targets(targets: list[str]) -> list[str]:
    seen = set()
    result = []
    for target in targets:
        key = target_key(target)
        if key in seen:
            continue
        seen.add(key)
        result.append(target)
    return result


def load_used_target_keys() -> set[str]:
    return read_keys_from_file(USED_BOTS_FILE) | read_keys_from_file(USED_CHANNEL_FILE)


def read_keys_from_file(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        keys.add(target_key(line.rsplit("\t", 1)[-1]))
    return keys


def load_low_target_keys() -> set[str]:
    return read_keys_from_file(LOW_BOTS_FILE) | read_keys_from_file(LOW_CHANNEL_FILE)


def remember_used_targets(campaign: dict, targets: list[str], input_path: Path) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    used_file = used_file_for_input(input_path)
    used_keys = load_used_target_keys()
    with used_file.open("a", encoding="utf-8") as file:
        for target in unique_targets(targets):
            key = target_key(target)
            if key in used_keys:
                continue
            file.write(f"{campaign['title']}\t{target}\n")
            used_keys.add(key)


def load_pending_targets(excluded_keys: set[str], input_path: Path | None = None) -> list[str]:
    pending_file = pending_file_for_input(input_path or INPUT_FILE)
    if not pending_file.exists():
        return []
    targets = []
    for line in pending_file.read_text(encoding="utf-8").splitlines():
        target = line.strip()
        if target and target_key(target) not in excluded_keys:
            targets.append(target)
    return unique_targets(targets)


def remember_pending_targets(targets: list[str], excluded_keys: set[str], input_path: Path) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    pending_file = pending_file_for_input(input_path)
    pending = load_pending_targets(excluded_keys, input_path)
    pending_keys = {target_key(target) for target in pending}
    for target in unique_targets(targets):
        key = target_key(target)
        if key in excluded_keys or key in pending_keys:
            continue
        pending.append(target)
        pending_keys.add(key)
    pending_file.write_text("\n".join(pending).rstrip() + ("\n" if pending else ""), encoding="utf-8")


def remove_pending_targets(targets: list[str], input_path: Path) -> None:
    pending_file = pending_file_for_input(input_path)
    if not pending_file.exists():
        return
    remove_keys = {target_key(target) for target in targets}
    pending = [
        target
        for target in load_pending_targets(set(), input_path)
        if target_key(target) not in remove_keys
    ]
    pending_file.write_text("\n".join(pending).rstrip() + ("\n" if pending else ""), encoding="utf-8")


def low_file_for_input(input_path: Path) -> Path:
    return LOW_CHANNEL_FILE if source_name(Path(input_path)) == "channel" else LOW_BOTS_FILE


def used_file_for_input(input_path: Path) -> Path:
    return USED_CHANNEL_FILE if source_name(Path(input_path)) == "channel" else USED_BOTS_FILE


def pending_file_for_input(input_path: Path) -> Path:
    return PENDING_CHANNEL_FILE if source_name(Path(input_path)) == "channel" else PENDING_BOTS_FILE


def remove_targets_by_keys_from_campaign_queue(campaigns: list[dict], start_index: int, keys: set[str]) -> None:
    index = start_index
    while index < len(campaigns):
        targets = [target for target in campaign_targets(campaigns[index]) if target_key(target) not in keys]
        set_campaign_targets(campaigns[index], targets)
        if not targets:
            campaigns.pop(index)
            continue
        index += 1


def make_retry_campaign(campaign: dict, rejected_bot: str, accepted_targets: list[str]) -> dict | None:
    rejected_key = target_key(rejected_bot)
    remembered_targets = unique_targets(accepted_targets)
    targets = unique_targets(
        remembered_targets + [bot for bot in campaign_targets(campaign) if target_key(bot) != rejected_key]
    )
    if not targets:
        return None

    retry_campaign = dict(campaign)
    retry_campaign["bots"] = targets
    retry_campaign["channels"] = targets
    retry_campaign["accepted_targets"] = remembered_targets
    retry_campaign["retry_count"] = int(campaign.get("retry_count", 0)) + 1
    return retry_campaign


def set_campaign_targets(campaign: dict, targets: list[str]) -> None:
    targets = unique_targets(targets)
    campaign["bots"] = targets
    campaign["channels"] = targets


def top_up_campaign_targets(campaigns: list[dict], start_index: int, campaign: dict, used_keys: set[str]) -> None:
    targets = unique_targets([target for target in campaign_targets(campaign) if target_key(target) not in used_keys])
    source_index = start_index
    while len(targets) < MIN_ACCEPTED_TARGETS and source_index < len(campaigns):
        source = campaigns[source_index]
        source_targets = [
            target for target in campaign_targets(source)
            if target_key(target) not in used_keys
        ]
        if not source_targets:
            campaigns.pop(source_index)
            continue

        moved_target = source_targets.pop(0)
        if target_key(moved_target) not in {target_key(target) for target in targets}:
            targets.append(moved_target)
        set_campaign_targets(source, source_targets)

        if not source_targets:
            campaigns.pop(source_index)

    set_campaign_targets(campaign, targets)


def remove_target_from_campaign_queue(campaigns: list[dict], start_index: int, rejected_bot: str) -> None:
    rejected_key = target_key(rejected_bot)
    index = start_index
    while index < len(campaigns):
        targets = [target for target in campaign_targets(campaigns[index]) if target_key(target) != rejected_key]
        set_campaign_targets(campaigns[index], targets)
        if not targets:
            campaigns.pop(index)
            continue
        index += 1


def wait_user_point(name: str) -> dict:
    input(f"Наведи мышь на '{name}' и нажми Enter в консоли...")
    x, y = pyautogui.position()
    print(f"{name}: x={x}, y={y}")
    return {"x": x, "y": y}


def calibrate() -> None:
    print("Открой страницу создания объявления в том же IE/окне.")
    print("Важно: сначала заполни Ad title, потом Ad text/описание. После этого поля сдвинутся в рабочие места для координат.")
    print("Тексты объявлений в скрипте рассчитаны примерно на 135-145 символов.")
    print("Для каждого поля наведи мышь прямо внутрь поля или на кнопку.")
    config = {
        "create_new_ad": wait_user_point("Create a new ad"),
        "bots_tab": wait_user_point("Target Bots tab"),
        "ad_title": wait_user_point("Ad title"),
        "ad_text": wait_user_point("Ad text"),
        "promote_url": wait_user_point("URL you want to promote"),
        "cpm": wait_user_point("price per 1000 impressions / CPM"),
        "budget": wait_user_point("budget"),
        "target_channels": wait_user_point("Target specific bots"),
        "terms": wait_user_point("I agree with Terms of Service checkbox"),
        "submit": wait_user_point("final create/submit button"),
    }
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved coordinates to {CONFIG_FILE}")


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise SystemExit("Нет screen_coords.json. Сначала запусти: python telegram_ads_screen_auto.py --calibrate")
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def looks_like_small_channel_error() -> bool:
    # Screen mode cannot read IE DOM reliably. This is a placeholder for manual review mode.
    # The script still continues after every Enter; use --review if Telegram rejects channels often.
    return False


def fill_one_ad(
    config: dict,
    campaign: dict,
    input_path: Path,
    review: bool,
    skip_create_click: bool,
    cpm: str,
    budget: str,
    strict: bool,
    leave_terms: bool = False,
    fill_only: bool = False,
) -> dict:
    number = campaign_number(campaign)
    print(f"Fill ad number {number}: {campaign['title']}")
    try:
        text_index = max(int(number) - 1, 0) % len(AD_TEXTS)
    except ValueError:
        text_index = 0
    ad_text = campaign.get("text") or AD_TEXTS[text_index]

    if not skip_create_click:
        check_stop()
        click_point(config, "create_new_ad")
        sleep_checked(0.8)
        reset_form_scroll()

    if click_optional_point(config, "bots_tab", "channels_tab"):
        sleep_checked(0.35)

    fill_after_label(config, "ad_title_label", "ad_title", campaign["title"])

    fill_after_label(config, "ad_text_label", "ad_text", ad_text)

    fill_after_label(config, "promote_url_label", "promote_url", PROMOTE_URL)

    fill_after_label(config, "cpm_label", "cpm", normalize_cpm(campaign.get("cpm", cpm)))

    fill_after_label(config, "budget_label", "budget", campaign.get("budget", budget))
    pyautogui.press("esc")
    sleep_checked(0.35)
    reset_form_scroll()

    daily_views = str(campaign.get("daily_views", "1"))
    if daily_views != "1" and f"daily_views_{daily_views}" in config:
        ensure_blue_option_selected(config, f"daily_views_{daily_views}")
        sleep_checked(0.2)

    if "active_status" in config:
        sleep_checked(0.35)
        ensure_blue_option_selected(config, "active_status")
        sleep_checked(0.3)

    if "terms" in config and not leave_terms:
        sleep_checked(0.6)
        ensure_checkbox_checked(config, "terms")
        sleep_checked(0.4)

    remembered_targets = unique_targets(campaign.get("accepted_targets", []))
    accepted_targets = []
    if remembered_targets:
        print(f"Memory window has {len(remembered_targets)} OK bot(s): {', '.join(remembered_targets)}")
    for bot in campaign_targets(campaign):
        check_stop()
        focus_target_bots_input(config)
        paste_channel_from_clipboard(bot)
        sleep_checked(0.4)
        if target_bot_daily_users_error_visible(config):
            print(
                f"Rejected target in {campaign['title']} / block {campaign.get('block_number', '?')}: "
                f"{bot}."
            )
            remember_low_bot(campaign, bot, input_path)
            print(
                f"Accepted before error: {len(accepted_targets)}. Need {MIN_ACCEPTED_TARGETS}. "
                "Clear draft and retry this ad without rejected bot."
            )
            reset_after_rejected_bot(config)
            return {
                "created": False,
                "retry": make_retry_campaign(campaign, bot, accepted_targets),
                "rejected_bot": bot,
                "accepted_targets": accepted_targets,
            }

        accepted_targets.append(bot)
        if len(accepted_targets) >= MIN_ACCEPTED_TARGETS:
            break

    if target_bot_daily_users_error_visible(config):
        print(
            f"Channel error still visible for {campaign['title']} / block {campaign.get('block_number', '?')}. "
            "Clearing draft and retrying."
        )
        reset_after_rejected_bot(config)
        retry_campaign = dict(campaign)
        retry_campaign["accepted_targets"] = unique_targets(accepted_targets)
        retry_campaign["retry_count"] = int(campaign.get("retry_count", 0)) + 1
        return {"created": False, "retry": retry_campaign, "rejected_bot": None, "accepted_targets": accepted_targets}

    if len(accepted_targets) < MIN_ACCEPTED_TARGETS:
        print(
            f"Skipping {campaign['title']} / block {campaign.get('block_number', '?')}: "
            f"only {len(accepted_targets)} accepted target(s), need {MIN_ACCEPTED_TARGETS}."
        )
        reset_after_rejected_bot(config)
        retry_campaign = dict(campaign)
        retry_campaign["accepted_targets"] = unique_targets(accepted_targets)
        retry_campaign["retry_count"] = int(campaign.get("retry_count", 0)) + 1
        return {"created": False, "retry": retry_campaign, "rejected_bot": None, "accepted_targets": accepted_targets}

    if fill_only:
        print(f"Filled {campaign['title']}. Create Ad was not clicked.")
        return {"created": False, "retry": None, "rejected_bot": None, "accepted_targets": accepted_targets}

    if review:
        print(f"Filled {campaign['title']}. Submit manually, then press Enter here.")
        input()
        refresh_page_after_create()
        return {"created": True, "retry": None, "rejected_bot": None, "accepted_targets": accepted_targets}
    else:
        check_stop()
        reset_form_scroll()
        click_point(config, "submit")
        sleep_checked(0.8)
        refresh_page_after_create()
        return {"created": True, "retry": None, "rejected_bot": None, "accepted_targets": accepted_targets}


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    start_emergency_stop_listener()

    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true", help="Save mouse coordinates for the current IE/window layout.")
    parser.add_argument("--input", type=Path, default=INPUT_FILE)
    parser.add_argument("--start-number", type=int, default=None)
    parser.add_argument("--start-block", type=int, default=None, help="First numbered block from bots.txt to process.")
    parser.add_argument("--use-file-titles", action="store_true")
    parser.add_argument("--review", action="store_true", help="Fill forms but do not click final submit button.")
    parser.add_argument("--skip-create-click", action="store_true", help="Use when the New Ad form is already open.")
    parser.add_argument("--cpm", default="0.5", help="CPM in TON. Values below 0.5 are raised to 0.5.")
    parser.add_argument("--budget", default="0.7", help="Initial budget in TON.")
    parser.add_argument("--limit", type=int, default=0, help="Process only first N ads; 0 means all.")
    parser.add_argument("--no-strict", action="store_true", help="Do not verify text after filling fields.")
    parser.add_argument("--leave-terms", action="store_true", help="Do not click Terms checkbox.")
    parser.add_argument("--fill-only", action="store_true", help="Fill the form and stop without waiting or clicking Create Ad.")
    parser.add_argument("--test-clipboard", action="store_true", help="Test native Windows clipboard write/read and exit.")
    parser.add_argument("--test-paste", action="store_true", help="Wait 3 seconds, then paste test text into the focused field.")
    parser.add_argument("--speed", type=float, default=2.0, help="Automation speed multiplier. Use 1 for old speed.")
    args = parser.parse_args()

    global SPEED
    SPEED = max(args.speed, 0.2)
    pyautogui.PAUSE = max(0.08 / SPEED, 0.01)

    if args.test_clipboard:
        test_text = "Боты 42"
        set_clipboard_text(test_text)
        actual = get_clipboard_text()
        print(f"Clipboard: {actual!r}")
        if actual != test_text:
            raise SystemExit("Clipboard test failed.")
        return

    if args.test_paste:
        print("Click the target input field now. Pasting in 3 seconds...")
        time.sleep(3)
        paste_via_shift_insert("Боты 42", clear=True)
        print("Paste test done.")
        return

    if args.calibrate:
        calibrate()
        return

    if args.start_block is None:
        try:
            raw_start_block = input("Start from block number [1]: ").strip()
        except EOFError:
            raw_start_block = ""
        try:
            args.start_block = int(raw_start_block) if raw_start_block else 1
        except ValueError:
            raise SystemExit("Start block must be an integer, for example 12.")

    if args.start_number is None:
        args.start_number = args.start_block

    config = load_config()
    campaigns = load_campaigns(args.input, args.start_number, args.use_file_titles, args.start_block)
    if args.limit:
        campaigns = campaigns[: args.limit]
    excluded_target_keys = load_used_target_keys() | load_low_target_keys()
    pending_file = pending_file_for_input(args.input)
    low_file = low_file_for_input(args.input)
    pending_targets = load_pending_targets(excluded_target_keys, args.input)
    if pending_targets:
        pending_campaign = dict(campaigns[0]) if campaigns else {"text": "", "daily_views": "1"}
        set_campaign_targets(pending_campaign, pending_targets)
        pending_campaign["block_number"] = "pending"
        pending_campaign["accepted_targets"] = []
        campaigns.insert(0, pending_campaign)
        print(f"Loaded pending target window: {len(pending_targets)} bot(s).")
    remove_targets_by_keys_from_campaign_queue(campaigns, 0, excluded_target_keys)
    print(f"Loaded excluded target history: {len(excluded_target_keys)} bot(s) from used/low files.")

    print("Do not move the IE/window while the script is running.")
    sleep_checked(3)

    index = 0
    created_count = 0
    rejected_count = 0
    next_ad_number = args.start_number
    while index < len(campaigns):
        campaign = campaigns[index]
        index += 1
        retry_count = int(campaign.get("retry_count", 0))
        remembered_targets = unique_targets(campaign.get("accepted_targets", []))
        if retry_count > MAX_RETRY_ATTEMPTS and not remembered_targets:
            print(
                f"Skipping {campaign['title']}: retry limit {MAX_RETRY_ATTEMPTS} reached."
            )
            continue
        excluded_target_keys = load_used_target_keys() | load_low_target_keys()
        set_campaign_targets(
            campaign,
            [target for target in campaign_targets(campaign) if target_key(target) not in excluded_target_keys],
        )
        top_up_campaign_targets(campaigns, index, campaign, excluded_target_keys)
        if len(campaign_targets(campaign)) < MIN_ACCEPTED_TARGETS:
            remember_pending_targets(campaign_targets(campaign), excluded_target_keys, args.input)
            print(
                f"Skipping {campaign['title']}: only {len(campaign_targets(campaign))} unique target(s) left, "
                f"need {MIN_ACCEPTED_TARGETS}. Saved to {pending_file}."
            )
            continue
        campaign["title"] = f"{source_title_prefix(args.input)} {next_ad_number}"
        check_stop()
        print(
            f"Creating; fill number {campaign_number(campaign)} / block {campaign.get('block_number', '?')}: "
            f"{campaign['title']}: {', '.join(campaign_targets(campaign))}"
        )
        result = fill_one_ad(
            config,
            campaign,
            args.input,
            args.review,
            args.skip_create_click and index == 1,
            args.cpm,
            args.budget,
            not args.no_strict,
            args.leave_terms,
            args.fill_only,
        )

        if result["created"]:
            accepted_targets = unique_targets(result.get("accepted_targets", []))
            remember_used_targets(campaign, accepted_targets, args.input)
            remove_pending_targets(accepted_targets, args.input)
            excluded_target_keys = load_used_target_keys() | load_low_target_keys()
            created_count += 1
            next_ad_number += 1
            for accepted_bot in accepted_targets:
                remove_target_from_campaign_queue(campaigns, index, accepted_bot)
            remove_targets_by_keys_from_campaign_queue(campaigns, index, excluded_target_keys)
            continue

        if result["rejected_bot"]:
            rejected_count += 1
            remove_pending_targets([result["rejected_bot"]], args.input)
            remove_target_from_campaign_queue(campaigns, index, result["rejected_bot"])

        retry_campaign = result["retry"]
        if retry_campaign:
            campaigns.insert(index, retry_campaign)
            remembered_targets = retry_campaign.get("accepted_targets", [])
            print(
                f"Retrying this campaign next: {retry_campaign['title']} "
                f"with {len(campaign_targets(retry_campaign))} target(s). "
                f"Remembered OK: {len(remembered_targets)}"
                f"{': ' + ', '.join(remembered_targets) if remembered_targets else ''}."
            )

    print(f"Done. Created: {created_count}. Rejected targets: {rejected_count}. Low targets file: {low_file}")


if __name__ == "__main__":
    main()
