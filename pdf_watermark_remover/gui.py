from __future__ import annotations

import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fitz
from PIL import Image, ImageTk

from .processor import SelectionProfile, WatermarkRegion, batch_remove_watermarks


class WatermarkRemoverApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PDF Watermark Remover")
        self.geometry("1380x860")
        self.minsize(1180, 720)

        self.profile = SelectionProfile()
        self.document: fitz.Document | None = None
        self.current_pdf: Path | None = None
        self.current_page_index = 0
        self.zoom = 1.6
        self.page_size = (0, 0)
        self.page_photo: ImageTk.PhotoImage | None = None
        self.drag_start: tuple[float, float] | None = None
        self.preview_rect_id: int | None = None
        self.overlay_ids: list[int] = []
        self.worker_thread: Thread | None = None
        self.worker_queue: Queue[tuple[str, object]] = Queue()

        self.sample_pdf_var = tk.StringVar()
        self.page_var = tk.StringVar(value="页码: - / -")
        self.status_var = tk.StringVar(value="打开一个 PDF 开始标注水印区域")
        self.batch_input_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="cover")
        self.use_normalized_var = tk.BooleanVar(value=True)
        self.recursive_var = tk.BooleanVar(value=False)
        self.progress_var = tk.DoubleVar(value=0.0)

        self._build_ui()
        self._update_json_preview()
        self.after(120, self._poll_worker_queue)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(12, 10))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)

        ttk.Button(toolbar, text="打开 PDF", command=self.open_pdf).grid(row=0, column=0, padx=(0, 8))
        ttk.Label(toolbar, textvariable=self.sample_pdf_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(toolbar, text="上一页", command=lambda: self.change_page(-1)).grid(row=0, column=2, padx=(12, 4))
        ttk.Button(toolbar, text="下一页", command=lambda: self.change_page(1)).grid(row=0, column=3, padx=4)
        ttk.Label(toolbar, textvariable=self.page_var).grid(row=0, column=4, padx=(10, 12))
        ttk.Button(toolbar, text="缩小", command=lambda: self.change_zoom(-0.2)).grid(row=0, column=5, padx=4)
        ttk.Button(toolbar, text="放大", command=lambda: self.change_zoom(0.2)).grid(row=0, column=6, padx=4)

        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))

        left = ttk.Frame(main)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        main.add(left, weight=5)

        canvas_frame = ttk.Frame(left)
        canvas_frame.grid(row=0, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_frame, bg="#f4f6f8", highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")

        x_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        y_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)

        self.canvas.bind("<ButtonPress-1>", self.on_drag_start)
        self.canvas.bind("<B1-Motion>", self.on_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_drag_end)

        hint = ttk.Label(
            left,
            text="操作方式: 打开示例 PDF 后，在预览页里拖拽框选水印区域。坐标会自动换算成 PDF 坐标，并可直接导出 JSON 或批量处理。",
            padding=(0, 8, 0, 0),
        )
        hint.grid(row=1, column=0, sticky="ew")

        right = ttk.Frame(main, padding=(6, 0, 0, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=2)
        right.rowconfigure(1, weight=2)
        main.add(right, weight=3)

        self._build_regions_panel(right)
        self._build_batch_panel(right)

        status_bar = ttk.Frame(self, padding=(12, 0, 12, 12))
        status_bar.grid(row=2, column=0, sticky="ew")
        status_bar.columnconfigure(0, weight=1)
        ttk.Label(status_bar, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Progressbar(status_bar, variable=self.progress_var, maximum=100).grid(row=0, column=1, sticky="ew", padx=(12, 0))

    def _build_regions_panel(self, parent: ttk.Frame) -> None:
        region_frame = ttk.LabelFrame(parent, text="水印区域", padding=10)
        region_frame.grid(row=0, column=0, sticky="nsew")
        region_frame.columnconfigure(0, weight=1)
        region_frame.rowconfigure(0, weight=1)

        self.region_list = tk.Listbox(region_frame, height=10)
        self.region_list.grid(row=0, column=0, columnspan=3, sticky="nsew")

        ttk.Button(region_frame, text="删除选中", command=self.remove_selected_region).grid(row=1, column=0, sticky="ew", pady=(8, 0), padx=(0, 6))
        ttk.Button(region_frame, text="清空全部", command=self.clear_regions).grid(row=1, column=1, sticky="ew", pady=(8, 0), padx=6)
        ttk.Button(region_frame, text="复制 JSON", command=self.copy_json).grid(row=1, column=2, sticky="ew", pady=(8, 0), padx=(6, 0))

        ttk.Button(region_frame, text="导入 JSON", command=self.import_profile).grid(row=2, column=0, sticky="ew", pady=(8, 0), padx=(0, 6))
        ttk.Button(region_frame, text="导出 JSON", command=self.export_profile).grid(row=2, column=1, sticky="ew", pady=(8, 0), padx=6)
        ttk.Button(region_frame, text="从当前 PDF 生成输入路径", command=self.use_current_pdf_as_batch_input).grid(row=2, column=2, sticky="ew", pady=(8, 0), padx=(6, 0))

        preview_frame = ttk.LabelFrame(parent, text="坐标预览", padding=10)
        preview_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.json_preview = tk.Text(preview_frame, height=16, wrap="none")
        self.json_preview.grid(row=0, column=0, sticky="nsew")
        self.json_preview.configure(state="disabled")

    def _build_batch_panel(self, parent: ttk.Frame) -> None:
        batch_frame = ttk.LabelFrame(parent, text="批量去水印", padding=10)
        batch_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        batch_frame.columnconfigure(1, weight=1)

        ttk.Label(batch_frame, text="输入路径").grid(row=0, column=0, sticky="w")
        ttk.Entry(batch_frame, textvariable=self.batch_input_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(batch_frame, text="选文件", command=self.choose_batch_file).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(batch_frame, text="选目录", command=self.choose_batch_dir).grid(row=0, column=3)

        ttk.Label(batch_frame, text="输出目录").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(batch_frame, textvariable=self.output_dir_var).grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(batch_frame, text="选择", command=self.choose_output_dir).grid(row=1, column=2, sticky="ew", pady=(8, 0), padx=(0, 4))
        ttk.Button(batch_frame, text="打开目录", command=self.open_output_dir).grid(row=1, column=3, sticky="ew", pady=(8, 0))

        ttk.Label(batch_frame, text="处理模式").grid(row=2, column=0, sticky="w", pady=(10, 0))
        mode_box = ttk.Combobox(batch_frame, textvariable=self.mode_var, state="readonly", values=["cover", "redact"])
        mode_box.grid(row=2, column=1, sticky="w", padx=8, pady=(10, 0))
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self._sync_mode())

        ttk.Checkbutton(batch_frame, text="按页面比例适配坐标", variable=self.use_normalized_var).grid(row=3, column=1, sticky="w", padx=8, pady=(10, 0))
        ttk.Checkbutton(batch_frame, text="递归处理子目录", variable=self.recursive_var).grid(row=4, column=1, sticky="w", padx=8, pady=(4, 0))

        ttk.Label(
            batch_frame,
            text="cover = 白块覆盖；redact = 真正删掉区域内容。若水印压在正文上，redact 可能一起删掉正文。",
            foreground="#666666",
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 0))

        self.run_button = ttk.Button(batch_frame, text="开始批量去水印", command=self.start_batch_job)
        self.run_button.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(12, 0))

    def open_pdf(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择 PDF",
            filetypes=[("PDF Files", "*.pdf")],
        )
        if not file_path:
            return
        self.load_pdf(Path(file_path))

    def load_pdf(self, file_path: Path) -> None:
        if self.document:
            self.document.close()
        self.document = fitz.open(file_path)
        self.current_pdf = file_path
        self.current_page_index = 0
        self.profile.sample_pdf = str(file_path)
        self.profile.sample_page_index = 0
        self.sample_pdf_var.set(str(file_path))
        self.batch_input_var.set(str(file_path))
        default_output = file_path.parent / "output"
        self.output_dir_var.set(str(default_output))
        self.status_var.set("已加载示例 PDF，拖拽框选水印位置即可生成坐标")
        self.refresh_region_views()
        self.render_page()

    def render_page(self) -> None:
        if not self.document:
            return

        page = self.document.load_page(self.current_page_index)
        matrix = fitz.Matrix(self.zoom, self.zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        self.page_photo = ImageTk.PhotoImage(image)
        self.page_size = (pixmap.width, pixmap.height)

        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.page_photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, pixmap.width, pixmap.height))
        self.page_var.set(f"页码: {self.current_page_index + 1} / {self.document.page_count}")
        self._draw_region_overlays()

    def change_page(self, delta: int) -> None:
        if not self.document:
            return
        next_page = self.current_page_index + delta
        if 0 <= next_page < self.document.page_count:
            self.current_page_index = next_page
            self.render_page()

    def change_zoom(self, delta: float) -> None:
        if not self.document:
            return
        self.zoom = max(0.6, min(4.0, round(self.zoom + delta, 2)))
        self.render_page()

    def on_drag_start(self, event: tk.Event) -> None:
        if not self.document:
            return
        x, y = self._clamp_canvas_point(event)
        if x is None or y is None:
            return
        self.drag_start = (x, y)
        if self.preview_rect_id:
            self.canvas.delete(self.preview_rect_id)
        self.preview_rect_id = self.canvas.create_rectangle(x, y, x, y, outline="#ff4d4f", width=2, dash=(6, 3))

    def on_drag_motion(self, event: tk.Event) -> None:
        if not self.drag_start or not self.preview_rect_id:
            return
        x, y = self._clamp_canvas_point(event)
        if x is None or y is None:
            return
        start_x, start_y = self.drag_start
        self.canvas.coords(self.preview_rect_id, start_x, start_y, x, y)

    def on_drag_end(self, event: tk.Event) -> None:
        if not self.document or not self.drag_start:
            return
        x, y = self._clamp_canvas_point(event)
        start_x, start_y = self.drag_start
        self.drag_start = None

        if self.preview_rect_id:
            self.canvas.delete(self.preview_rect_id)
            self.preview_rect_id = None

        if x is None or y is None:
            return

        if abs(x - start_x) < 8 or abs(y - start_y) < 8:
            self.status_var.set("选区太小，已忽略。请重新拖拽一个更明确的矩形区域")
            return

        page = self.document.load_page(self.current_page_index)
        pdf_rect = self._canvas_rect_to_pdf_rect(page.rect, start_x, start_y, x, y)
        region = WatermarkRegion(
            label=f"区域 {len(self.profile.regions) + 1}",
            x0=pdf_rect.x0,
            y0=pdf_rect.y0,
            x1=pdf_rect.x1,
            y1=pdf_rect.y1,
            page_width=page.rect.width,
            page_height=page.rect.height,
        )
        self.profile.regions.append(region)
        self.profile.sample_page_index = self.current_page_index
        self._sync_mode()
        self.refresh_region_views()
        self.status_var.set(f"已新增 {region.label}，可继续框选多个水印区域")

    def _clamp_canvas_point(self, event: tk.Event) -> tuple[float | None, float | None]:
        if not self.page_size[0] or not self.page_size[1]:
            return (None, None)

        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        x = min(max(x, 0), self.page_size[0])
        y = min(max(y, 0), self.page_size[1])
        return x, y

    def _canvas_rect_to_pdf_rect(
        self,
        page_rect: fitz.Rect,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> fitz.Rect:
        image_width, image_height = self.page_size
        scale_x = page_rect.width / image_width
        scale_y = page_rect.height / image_height
        return fitz.Rect(
            min(x0, x1) * scale_x,
            min(y0, y1) * scale_y,
            max(x0, x1) * scale_x,
            max(y0, y1) * scale_y,
        )

    def _pdf_rect_to_canvas_coords(self, page_rect: fitz.Rect, rect: fitz.Rect) -> tuple[float, float, float, float]:
        image_width, image_height = self.page_size
        scale_x = image_width / page_rect.width
        scale_y = image_height / page_rect.height
        return (
            rect.x0 * scale_x,
            rect.y0 * scale_y,
            rect.x1 * scale_x,
            rect.y1 * scale_y,
        )

    def _draw_region_overlays(self) -> None:
        for overlay_id in self.overlay_ids:
            self.canvas.delete(overlay_id)
        self.overlay_ids.clear()

        if not self.document:
            return

        page = self.document.load_page(self.current_page_index)
        for region in self.profile.regions:
            rect = region.rect_for_page(page.rect, use_normalized=True)
            x0, y0, x1, y1 = self._pdf_rect_to_canvas_coords(page.rect, rect)
            box_id = self.canvas.create_rectangle(x0, y0, x1, y1, outline="#ff4d4f", width=2)
            text_id = self.canvas.create_text(
                x0 + 6,
                max(y0 - 12, 12),
                anchor="w",
                text=region.label,
                fill="#b42318",
                font=("Microsoft YaHei UI", 10, "bold"),
            )
            self.overlay_ids.extend([box_id, text_id])

    def refresh_region_views(self) -> None:
        self.region_list.delete(0, tk.END)
        for region in self.profile.regions:
            self.region_list.insert(
                tk.END,
                f"{region.label}: ({region.x0:.1f}, {region.y0:.1f}) - ({region.x1:.1f}, {region.y1:.1f})",
            )
        self._draw_region_overlays()
        self._update_json_preview()

    def _update_json_preview(self) -> None:
        self.json_preview.configure(state="normal")
        self.json_preview.delete("1.0", tk.END)
        self.json_preview.insert("1.0", self.profile.to_json())
        self.json_preview.configure(state="disabled")

    def remove_selected_region(self) -> None:
        selection = self.region_list.curselection()
        if not selection:
            return
        index = selection[0]
        removed = self.profile.regions.pop(index)
        self.refresh_region_views()
        self.status_var.set(f"已删除 {removed.label}")

    def clear_regions(self) -> None:
        if not self.profile.regions:
            return
        self.profile.regions.clear()
        self.refresh_region_views()
        self.status_var.set("已清空全部水印区域")

    def export_profile(self) -> None:
        if not self.profile.regions:
            messagebox.showwarning("没有坐标", "请先框选至少一个水印区域")
            return
        target = filedialog.asksaveasfilename(
            title="导出坐标 JSON",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
        )
        if not target:
            return
        self.profile.save(target)
        self.status_var.set(f"已导出坐标到 {target}")

    def import_profile(self) -> None:
        source = filedialog.askopenfilename(
            title="导入坐标 JSON",
            filetypes=[("JSON Files", "*.json")],
        )
        if not source:
            return
        self.profile = SelectionProfile.load(source)
        self.mode_var.set(self.profile.mode)
        self.refresh_region_views()
        self.status_var.set(f"已导入 {len(self.profile.regions)} 个水印区域")

    def copy_json(self) -> None:
        content = self.profile.to_json()
        self.clipboard_clear()
        self.clipboard_append(content)
        self.status_var.set("坐标 JSON 已复制到剪贴板")

    def choose_batch_file(self) -> None:
        selected = filedialog.askopenfilename(title="选择单个 PDF", filetypes=[("PDF Files", "*.pdf")])
        if selected:
            self.batch_input_var.set(selected)

    def choose_batch_dir(self) -> None:
        selected = filedialog.askdirectory(title="选择批量输入目录")
        if selected:
            self.batch_input_var.set(selected)

    def choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="选择输出目录")
        if selected:
            self.output_dir_var.set(selected)

    def resolve_output_dir(self) -> Path | None:
        output_dir = self.output_dir_var.get().strip()
        if output_dir:
            return Path(output_dir)

        input_path = self.batch_input_var.get().strip()
        if input_path:
            source = Path(input_path)
            resolved = (source.parent if source.is_file() else source) / "output"
            self.output_dir_var.set(str(resolved))
            return resolved

        if self.current_pdf:
            resolved = self.current_pdf.parent / "output"
            self.output_dir_var.set(str(resolved))
            return resolved

        return None

    def open_output_dir(self) -> None:
        output_dir = self.resolve_output_dir()
        if output_dir is None:
            messagebox.showwarning("缺少输出目录", "请先选择输出目录，或先打开一个示例 PDF")
            return

        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            if os.name == "nt":
                os.startfile(output_dir)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(output_dir)])
            else:
                subprocess.Popen(["xdg-open", str(output_dir)])
            self.status_var.set(f"已打开输出目录: {output_dir}")
        except Exception as exc:  # pragma: no cover - UI feedback path
            messagebox.showerror("打开失败", f"无法打开输出目录：{exc}")

    def use_current_pdf_as_batch_input(self) -> None:
        if self.current_pdf:
            self.batch_input_var.set(str(self.current_pdf))
            self.status_var.set("已将当前示例 PDF 填充到批量输入路径")

    def _sync_mode(self) -> None:
        self.profile.mode = self.mode_var.get()
        self._update_json_preview()

    def start_batch_job(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return
        if not self.profile.regions:
            messagebox.showwarning("没有坐标", "请先框选至少一个水印区域")
            return

        input_path = self.batch_input_var.get().strip()
        if not input_path:
            if not self.current_pdf:
                messagebox.showwarning("缺少输入", "请选择批量输入路径，或先打开一个示例 PDF")
                return
            input_path = str(self.current_pdf)
            self.batch_input_var.set(input_path)

        output_dir_path = self.resolve_output_dir()
        if output_dir_path is None:
            messagebox.showwarning("缺少输出目录", "请先选择输出目录")
            return
        output_dir = str(output_dir_path)

        self._sync_mode()
        self.progress_var.set(0.0)
        self.run_button.configure(state="disabled")
        self.status_var.set("正在批量处理 PDF，请稍候")

        self.worker_thread = Thread(
            target=self._run_batch_job,
            args=(input_path, output_dir),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_batch_job(self, input_path: str, output_dir: str) -> None:
        try:
            results = batch_remove_watermarks(
                input_path=input_path,
                output_dir=output_dir,
                profile=self.profile,
                recursive=self.recursive_var.get(),
                use_normalized=self.use_normalized_var.get(),
                progress_callback=self._queue_progress,
            )
            self.worker_queue.put(("done", results))
        except Exception as exc:  # pragma: no cover - UI feedback path
            self.worker_queue.put(("error", str(exc)))

    def _queue_progress(self, index: int, total: int, pdf_path: Path) -> None:
        self.worker_queue.put(("progress", (index, total, str(pdf_path))))

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                event, payload = self.worker_queue.get_nowait()
                if event == "progress":
                    index, total, pdf_path = payload
                    progress = (index / total) * 100 if total else 0
                    self.progress_var.set(progress)
                    self.status_var.set(f"处理中 {index}/{total}: {pdf_path}")
                elif event == "done":
                    self.progress_var.set(100.0)
                    self.run_button.configure(state="normal")
                    results = payload
                    self.status_var.set(f"处理完成，共输出 {len(results)} 个 PDF")
                    output_dir = self.resolve_output_dir()
                    if output_dir is not None:
                        messagebox.showinfo(
                            "处理完成",
                            f"批量任务完成，共生成 {len(results)} 个 PDF\n输出目录：{output_dir}",
                        )
                    else:
                        messagebox.showinfo("处理完成", f"批量任务完成，共生成 {len(results)} 个 PDF")
                elif event == "error":
                    self.run_button.configure(state="normal")
                    self.progress_var.set(0.0)
                    self.status_var.set("处理失败，请检查输入路径或日志信息")
                    messagebox.showerror("处理失败", str(payload))
        except Empty:
            pass
        finally:
            self.after(120, self._poll_worker_queue)

    def destroy(self) -> None:
        if self.document:
            self.document.close()
        super().destroy()


def run() -> None:
    app = WatermarkRemoverApp()
    app.mainloop()
