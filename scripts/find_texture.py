from pathlib import Path

import click
import numpy as np

try:
    import cv2

    METHODS = [
        cv2.TM_CCOEFF_NORMED,
        cv2.TM_CCORR_NORMED,
    ]

    def load_gray(path: Path) -> np.ndarray | None:
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"  [warn] could not read '{path}' – skipping")
        return img

    def match_single_scale(source_gray: np.ndarray, template_gray: np.ndarray, threshold: float) -> list[dict]:
        th, tw = template_gray.shape[:2]
        sh, sw = source_gray.shape[:2]

        if th > sh or tw > sw:
            return []

        hits = []
        for method in METHODS:
            result = cv2.matchTemplate(source_gray, template_gray, method)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val >= threshold:
                tl = max_loc
                br = (tl[0] + tw, tl[1] + th)
                hits.append({"score": float(max_val), "top_left": tl, "bottom_right": br, "method": method})
        return hits

    def search_image(
        source_path: Path,
        template_gray: np.ndarray,
        threshold: float,
        scale_min: float,
        scale_max: float,
        scale_steps: int,
    ) -> dict | None:
        source_gray = load_gray(source_path)
        if source_gray is None:
            return None

        best: dict | None = None
        scales = np.linspace(scale_min, scale_max, scale_steps)

        for scale in scales:
            new_w = max(1, int(template_gray.shape[1] * scale))
            new_h = max(1, int(template_gray.shape[0] * scale))
            resized = cv2.resize(template_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)

            hits = match_single_scale(source_gray, resized, threshold)
            for hit in hits:
                if best is None or hit["score"] > best["score"]:
                    best = {**hit, "scale": float(scale), "source_path": source_path}

        return best

    def annotate(source_path: Path, hit: dict) -> np.ndarray:
        img = cv2.imread(str(source_path))
        if img is None:
            return np.zeros((100, 400, 3), dtype=np.uint8)

        tl, br = hit["top_left"], hit["bottom_right"]
        cv2.rectangle(img, tl, br, (0, 255, 0), 2)
        label = f"score={hit['score']:.3f}  scale={hit['scale']:.2f}"
        cv2.putText(img, label, (tl[0], max(tl[1] - 8, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        return img

    @click.command()
    @click.argument("source_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
    @click.argument("target_image", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("--threshold", default=0.8, show_default=True, help="match confidence threshold (0–1)")
    @click.option("--scale-min", default=0.5, show_default=True, help="minimum scale factor")
    @click.option("--scale-max", default=1.5, show_default=True, help="maximum scale factor")
    @click.option("--scale-steps", default=20, show_default=True, help="number of scale steps")
    @click.option("--show", is_flag=True, help="preview matched images in a window")
    @click.option("--save-dir", default=None, type=click.Path(path_type=Path), help="directory to save annotated match images")
    def find_texture(
        source_dir: Path,
        target_image: Path,
        threshold: float,
        scale_min: float,
        scale_max: float,
        scale_steps: int,
        show: bool,
        save_dir: Path | None,
    ) -> None:
        template_gray = load_gray(target_image)
        if template_gray is None:
            raise click.ClickException("could not load target image")

        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)

        png_files = sorted(source_dir.rglob("*.png"))
        if not png_files:
            raise click.ClickException(f"no PNG files found under '{source_dir}'")

        print(f"target  : {target_image}  ({template_gray.shape[1]}×{template_gray.shape[0]} px)")
        print(f"sources : {len(png_files)} PNG(s) found under '{source_dir}'")
        print(f"settings: threshold={threshold}  scales=[{scale_min}, {scale_max}] × {scale_steps} steps")
        print("─" * 60)

        matches = []

        for i, png_path in enumerate(png_files, 1):
            print(f"[{i:>4}/{len(png_files)}] {png_path.relative_to(source_dir)} … ", end="", flush=True)

            hit = search_image(png_path, template_gray, threshold=threshold, scale_min=scale_min, scale_max=scale_max, scale_steps=scale_steps)

            if hit:
                tl, br = hit["top_left"], hit["bottom_right"]
                print(f"MATCH  score={hit['score']:.4f}  scale={hit['scale']:.2f}  at ({tl[0]},{tl[1]})→({br[0]},{br[1]})")
                matches.append(hit)

                annotated = annotate(png_path, hit)

                if save_dir:
                    out_path = save_dir / (png_path.stem + "_match.png")
                    cv2.imwrite(str(out_path), annotated)
                    print(f"          saved → {out_path}")

                if show:
                    cv2.imshow(f"match – {png_path.name}", annotated)
                    print("          [press any key to continue]")
                    cv2.waitKey(0)
                    cv2.destroyAllWindows()
            else:
                print("no match")

        print("─" * 60)
        print(f"done. {len(matches)}/{len(png_files)} image(s) contained the target.")

        if matches:
            print("\nmatched files:")
            for h in sorted(matches, key=lambda x: x["score"], reverse=True):
                rel = h["source_path"].relative_to(source_dir)
                tl, br = h["top_left"], h["bottom_right"]
                print(f"  {h['score']:.4f}  {rel}  [({tl[0]},{tl[1]})→({br[0]},{br[1]})]  scale={h['scale']:.2f}")

except ImportError:

    @click.command()
    @click.argument("source_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
    @click.argument("target_image", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("--threshold", default=0.8, show_default=True, help="match confidence threshold (0–1)")
    @click.option("--scale-min", default=0.5, show_default=True, help="minimum scale factor")
    @click.option("--scale-max", default=1.5, show_default=True, help="maximum scale factor")
    @click.option("--scale-steps", default=20, show_default=True, help="number of scale steps")
    @click.option("--show", is_flag=True, help="preview matched images in a window")
    @click.option("--save-dir", default=None, type=click.Path(path_type=Path), help="directory to save annotated match images")
    def find_texture(
        source_dir: Path,
        target_image: Path,
        threshold: float,
        scale_min: float,
        scale_max: float,
        scale_steps: int,
        show: bool,
        save_dir: Path | None,
    ) -> None:
        raise click.ClickException("this script requires opencv (uv add opencv-python)")
