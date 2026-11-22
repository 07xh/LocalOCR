"""LocalOCR command line and loopback server entry point."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .settings import api_key
from .engine import OCRService, EngineUnavailable
from .image_io import load_image, InvalidImage


def main() -> int:
    parser = argparse.ArgumentParser(description="LocalOCR offline image text recognition")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="start loopback API")
    serve.add_argument("--port", type=int, default=18765)
    studio = sub.add_parser("studio", help="start API and open the local annotation workspace")
    studio.add_argument("--port", type=int, default=18765)
    studio.add_argument("--no-browser", action="store_true", help="do not automatically open a browser")
    sub.add_parser("key", help="display local API key (keep private)")
    sub.add_parser("engines", help="show locally available OCR backends")
    doctor = sub.add_parser("doctor", help="check bundled models, local storage and Studio assets")
    doctor.add_argument("--deep", action="store_true", help="run synthetic local RapidOCR inference")

    recog = sub.add_parser("recognize", help="recognize a local image file")
    recog.add_argument("image", type=Path)
    recog.add_argument("--engine", choices=["auto", "rapidocr", "tesseract"], default="auto")
    args = parser.parse_args()
    if args.command == "key":
        print(api_key())
        return 0
    if args.command == "engines":
        print(json.dumps(OCRService.backends(), ensure_ascii=False))
        return 0
    if args.command == "doctor":
        from .doctor import diagnose
        report = diagnose(deep=args.deep)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report["ready"] else 1
    if args.command in ("serve", "studio"):
        if not 1024 <= args.port <= 65535:
            parser.error("port must be 1024-65535")
        import uvicorn
        print("LocalOCR API: http://127.0.0.1:%d/docs" % args.port)
        if args.command == "studio":
            print("LocalOCR studio: http://127.0.0.1:%d/studio" % args.port)
            if not args.no_browser:
                import threading
                import webbrowser
                threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:%d/studio" % args.port)).start()
        # Use a direct app import so frozen builds do not rely on dynamic module lookup.
        from .api import app
        uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1)
        return 0
    if args.command == "recognize":
        try:
            img = load_image(args.image.read_bytes())
            print(json.dumps(OCRService().run(img, args.engine).as_dict(), ensure_ascii=False, indent=2))
            return 0
        except (InvalidImage, EngineUnavailable, OSError) as e:
            parser.exit(1, "Error: %s\n" % e)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
