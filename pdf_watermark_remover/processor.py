from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable
import json

import fitz


ProgressCallback = Callable[[int, int, Path], None]


@dataclass(slots=True)
class WatermarkRegion:
    label: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_width: float
    page_height: float

    def __post_init__(self) -> None:
        self.x0, self.x1 = sorted((float(self.x0), float(self.x1)))
        self.y0, self.y1 = sorted((float(self.y0), float(self.y1)))
        self.page_width = float(self.page_width)
        self.page_height = float(self.page_height)

    @property
    def rect(self) -> fitz.Rect:
        return fitz.Rect(self.x0, self.y0, self.x1, self.y1)

    def normalized(self) -> dict[str, float]:
        if not self.page_width or not self.page_height:
            return {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0}
        return {
            "x0": self.x0 / self.page_width,
            "y0": self.y0 / self.page_height,
            "x1": self.x1 / self.page_width,
            "y1": self.y1 / self.page_height,
        }

    def rect_for_page(self, page_rect: fitz.Rect, use_normalized: bool = True) -> fitz.Rect:
        if use_normalized and self.page_width and self.page_height:
            normalized = self.normalized()
            return fitz.Rect(
                normalized["x0"] * page_rect.width,
                normalized["y0"] * page_rect.height,
                normalized["x1"] * page_rect.width,
                normalized["y1"] * page_rect.height,
            )

        scale_x = page_rect.width / self.page_width if self.page_width else 1.0
        scale_y = page_rect.height / self.page_height if self.page_height else 1.0
        return fitz.Rect(
            self.x0 * scale_x,
            self.y0 * scale_y,
            self.x1 * scale_x,
            self.y1 * scale_y,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "points": {
                "x0": round(self.x0, 3),
                "y0": round(self.y0, 3),
                "x1": round(self.x1, 3),
                "y1": round(self.y1, 3),
            },
            "page_size": {
                "width": round(self.page_width, 3),
                "height": round(self.page_height, 3),
            },
            "normalized": {key: round(value, 6) for key, value in self.normalized().items()},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "WatermarkRegion":
        points = payload.get("points", {})
        page_size = payload.get("page_size", {})
        return cls(
            label=str(payload.get("label", "区域")),
            x0=float(points.get("x0", 0.0)),
            y0=float(points.get("y0", 0.0)),
            x1=float(points.get("x1", 0.0)),
            y1=float(points.get("y1", 0.0)),
            page_width=float(page_size.get("width", 0.0)),
            page_height=float(page_size.get("height", 0.0)),
        )


@dataclass(slots=True)
class SelectionProfile:
    sample_pdf: str = ""
    sample_page_index: int = 0
    mode: str = "cover"
    regions: list[WatermarkRegion] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "sample_pdf": self.sample_pdf,
            "sample_page_index": self.sample_page_index,
            "mode": self.mode,
            "regions": [region.to_dict() for region in self.regions],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.write_text(self.to_json(), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "SelectionProfile":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        regions = [WatermarkRegion.from_dict(item) for item in payload.get("regions", [])]
        return cls(
            sample_pdf=str(payload.get("sample_pdf", "")),
            sample_page_index=int(payload.get("sample_page_index", 0)),
            mode=str(payload.get("mode", "cover")),
            regions=regions,
        )


def _iter_pdf_files(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            raise ValueError(f"输入文件不是 PDF: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise FileNotFoundError(f"找不到输入路径: {input_path}")

    pattern = "**/*.pdf" if recursive else "*.pdf"
    pdf_files = sorted(input_path.glob(pattern))
    if not pdf_files:
        raise FileNotFoundError(f"在 {input_path} 下没有找到 PDF 文件")
    return pdf_files


def _apply_cover(page: fitz.Page, rect: fitz.Rect, fill_rgb: tuple[float, float, float]) -> None:
    page.draw_rect(rect, color=fill_rgb, fill=fill_rgb, overlay=True, width=0)


def _apply_redact(page: fitz.Page, rect: fitz.Rect, fill_rgb: tuple[float, float, float]) -> None:
    page.add_redact_annot(rect, fill=fill_rgb)


def remove_watermarks_from_pdf(
    input_pdf: Path,
    output_pdf: Path,
    regions: Iterable[WatermarkRegion],
    mode: str = "cover",
    use_normalized: bool = True,
    fill_rgb: tuple[float, float, float] = (1, 1, 1),
) -> dict[str, object]:
    if mode not in {"cover", "redact"}:
        raise ValueError("mode 只能是 'cover' 或 'redact'")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    regions = list(regions)
    page_count = 0

    with fitz.open(input_pdf) as document:
        page_count = document.page_count
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            page_rect = page.rect
            page_regions = [region.rect_for_page(page_rect, use_normalized=use_normalized) for region in regions]

            if mode == "cover":
                for rect in page_regions:
                    _apply_cover(page, rect, fill_rgb)
            else:
                for rect in page_regions:
                    _apply_redact(page, rect, fill_rgb)
                if page_regions:
                    page.apply_redactions()

        document.save(output_pdf, garbage=4, deflate=True)

    return {
        "input": str(input_pdf),
        "output": str(output_pdf),
        "pages": page_count,
        "regions": len(regions),
        "mode": mode,
    }


def batch_remove_watermarks(
    input_path: str | Path,
    output_dir: str | Path,
    profile: SelectionProfile,
    recursive: bool = False,
    use_normalized: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, object]]:
    source = Path(input_path)
    destination_root = Path(output_dir)
    pdf_files = _iter_pdf_files(source, recursive=recursive)
    results: list[dict[str, object]] = []

    for index, pdf_file in enumerate(pdf_files, start=1):
        if source.is_dir():
            relative = pdf_file.relative_to(source)
            output_pdf = destination_root / relative.parent / f"{relative.stem}_cleaned.pdf"
        else:
            output_pdf = destination_root / f"{pdf_file.stem}_cleaned.pdf"

        result = remove_watermarks_from_pdf(
            input_pdf=pdf_file,
            output_pdf=output_pdf,
            regions=profile.regions,
            mode=profile.mode,
            use_normalized=use_normalized,
        )
        results.append(result)
        if progress_callback:
            progress_callback(index, len(pdf_files), pdf_file)

    return results
