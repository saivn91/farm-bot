import argparse
import os

import cv2

from core.models import TemplateThresholds
from core.vision import find_all


ROOT_DIR = os.path.dirname(__file__)
TEMPLATE_DIR = os.path.join(ROOT_DIR, "templates")
DEFAULT_SCREEN = os.path.join(TEMPLATE_DIR, "screen.png")
DEFAULT_THRESHOLD = 0.75


def normalize_template_name(name: str) -> str:
    if name.lower().endswith((".png", ".jpg", ".jpeg")):
        return name
    return f"{name}.png"


def threshold_for(template_name: str) -> float:
    thresholds = TemplateThresholds()
    threshold = thresholds.get(template_name)
    return threshold if threshold is not None else DEFAULT_THRESHOLD


def scan_template(template_input: str, screen_path: str = DEFAULT_SCREEN) -> str | None:
    template_name = normalize_template_name(template_input)
    template_key = os.path.splitext(template_name)[0]
    template_path = os.path.join(TEMPLATE_DIR, template_name)
    output_path = os.path.join(TEMPLATE_DIR, f"{template_key}_result.png")

    print(f"\n{'=' * 50}")
    print(f"DANG QUET TEMPLATE: {template_name}")
    print(f"SCREEN: {screen_path}")
    print(f"{'=' * 50}")

    screen = cv2.imread(screen_path, cv2.IMREAD_COLOR)
    if screen is None:
        print(f"Loi: Khong doc duoc anh screen: {screen_path}")
        return None

    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        print(f"Loi: Khong doc duoc template: {template_path}")
        return None

    threshold = threshold_for(template_name)
    matches = find_all(screen, template_name, thresh=threshold)
    template_h, template_w = template.shape[:2]

    out = screen.copy()
    for index, match in enumerate(matches, start=1):
        left = match.x - template_w // 2
        top = match.y - template_h // 2
        right = left + template_w
        bottom = top + template_h

        cv2.rectangle(out, (left, top), (right, bottom), (0, 255, 0), 2)
        cv2.circle(out, (match.x, match.y), 4, (0, 0, 255), -1)
        cv2.putText(
            out,
            f"{index}:{match.score:.2f}",
            (left, max(15, top - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 0),
            1,
        )

    cv2.imwrite(output_path, out)

    print(f"Threshold: {threshold:.2f}")
    print(f"Tim thay: {len(matches)} vi tri")
    for index, match in enumerate(matches, start=1):
        print(f"  {index}. x={match.x}, y={match.y}, score={match.score:.3f}")
    print(f"Da luu anh ket qua: {output_path}")

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Quet template trong templates/screen.png va ve khung ket qua."
    )
    parser.add_argument("template", help="Ten template, vi du: icon_game")
    parser.add_argument(
        "--screen",
        default=DEFAULT_SCREEN,
        help="Duong dan anh screen can quet. Mac dinh: templates/screen.png",
    )
    args = parser.parse_args()

    scan_template(args.template, args.screen)


if __name__ == "__main__":
    main()
