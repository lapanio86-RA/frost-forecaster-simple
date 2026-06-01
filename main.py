from __future__ import annotations

import datetime as dt
import os
import queue
import threading
import traceback
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, Y, filedialog, messagebox
import tkinter as tk
from tkinter import ttk

try:
    from PIL import Image, ImageTk
except Exception:  # noqa: BLE001
    Image = None
    ImageTk = None

from frost_core import DOMAINS, compute_multiple_nights, fetch_openmeteo_grid, make_demo_grid
from plot_output import save_all_outputs


class FrostApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Frost Forecaster Simple")
        self.geometry("1120x760")
        self.minsize(980, 660)

        self.msg_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.image_paths: list[Path] = []
        self.current_photo = None

        self._build_ui()
        self.after(150, self._poll_queue)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=BOTH, expand=True)

        controls = ttk.LabelFrame(root, text="Configuração", padding=10)
        controls.pack(side=LEFT, fill=Y, padx=(0, 10))

        self.source_var = tk.StringVar(value="real")
        ttk.Label(controls, text="Fonte de dados").pack(anchor="w")
        ttk.Radiobutton(controls, text="Previsão real (Open-Meteo)", variable=self.source_var, value="real").pack(anchor="w")
        ttk.Radiobutton(controls, text="Demo offline", variable=self.source_var, value="demo").pack(anchor="w")

        ttk.Separator(controls).pack(fill="x", pady=8)

        ttk.Label(controls, text="Região").pack(anchor="w")
        self.domain_var = tk.StringVar(value="south_core")
        domain_names = [f"{d.key} | {d.name}" for d in DOMAINS.values()]
        self.domain_combo = ttk.Combobox(controls, values=domain_names, state="readonly", width=34)
        self.domain_combo.current(0)
        self.domain_combo.pack(anchor="w", pady=(0, 8))
        self.domain_combo.bind("<<ComboboxSelected>>", self._domain_changed)

        ttk.Label(controls, text="Resolução da grade (graus)").pack(anchor="w")
        self.step_var = tk.StringVar(value="0.5")
        ttk.Combobox(controls, textvariable=self.step_var, values=["1.0", "0.75", "0.5", "0.25"], width=10).pack(anchor="w", pady=(0, 8))

        today = dt.datetime.now().date()
        ttk.Label(controls, text="Primeira noite (AAAA-MM-DD)").pack(anchor="w")
        self.date_var = tk.StringVar(value=today.isoformat())
        ttk.Entry(controls, textvariable=self.date_var, width=14).pack(anchor="w", pady=(0, 8))

        ttk.Label(controls, text="Número de noites").pack(anchor="w")
        self.nights_var = tk.IntVar(value=5)
        ttk.Spinbox(controls, from_=1, to=7, textvariable=self.nights_var, width=8).pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(controls)
        row.pack(anchor="w", pady=(0, 8))
        ttk.Label(row, text="Janela BRT: ").pack(side=LEFT)
        self.start_hour_var = tk.IntVar(value=18)
        self.end_hour_var = tk.IntVar(value=9)
        ttk.Spinbox(row, from_=0, to=23, textvariable=self.start_hour_var, width=4).pack(side=LEFT)
        ttk.Label(row, text="h → ").pack(side=LEFT)
        ttk.Spinbox(row, from_=0, to=23, textvariable=self.end_hour_var, width=4).pack(side=LEFT)
        ttk.Label(row, text="h").pack(side=LEFT)

        ttk.Label(controls, text="Transparência abaixo de risco").pack(anchor="w")
        self.transparent_var = tk.StringVar(value="0.02")
        ttk.Combobox(controls, textvariable=self.transparent_var, values=["0.00", "0.01", "0.02", "0.05", "0.10"], width=10).pack(anchor="w", pady=(0, 8))

        self.include_metrics_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="Gerar mapas extras das variáveis", variable=self.include_metrics_var).pack(anchor="w", pady=(0, 8))

        ttk.Label(controls, text="Pasta de saída").pack(anchor="w")
        out_row = ttk.Frame(controls)
        out_row.pack(anchor="w", pady=(0, 8))
        self.output_var = tk.StringVar(value=str(Path.cwd() / "outputs"))
        ttk.Entry(out_row, textvariable=self.output_var, width=26).pack(side=LEFT)
        ttk.Button(out_row, text="...", command=self._choose_output).pack(side=LEFT, padx=(4, 0))

        self.generate_button = ttk.Button(controls, text="Gerar previsão", command=self._start_generate)
        self.generate_button.pack(fill="x", pady=(8, 4))
        ttk.Button(controls, text="Abrir pasta de saída", command=self._open_output).pack(fill="x")

        ttk.Separator(controls).pack(fill="x", pady=10)
        ttk.Label(controls, text="Imagens geradas").pack(anchor="w")
        self.listbox = tk.Listbox(controls, width=42, height=13)
        self.listbox.pack(fill="x")
        self.listbox.bind("<<ListboxSelect>>", self._on_select_image)

        main = ttk.Frame(root)
        main.pack(side=RIGHT, fill=BOTH, expand=True)

        self.status_text = tk.Text(main, height=9, wrap="word")
        self.status_text.pack(fill="x", pady=(0, 8))
        self._write_status("Pronto. Configure e clique em Gerar previsão.\n")

        preview_frame = ttk.LabelFrame(main, text="Pré-visualização", padding=6)
        preview_frame.pack(fill=BOTH, expand=True)
        self.preview_label = ttk.Label(preview_frame, text="Nenhuma imagem gerada ainda.", anchor="center")
        self.preview_label.pack(fill=BOTH, expand=True)

    def _domain_changed(self, _event=None) -> None:
        key = self._selected_domain_key()
        self.step_var.set(str(DOMAINS[key].recommended_step))

    def _selected_domain_key(self) -> str:
        value = self.domain_combo.get()
        return value.split("|", 1)[0].strip()

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.cwd()))
        if path:
            self.output_var.set(path)

    def _open_output(self) -> None:
        path = Path(self.output_var.get())
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # Windows-focused project

    def _write_status(self, msg: str) -> None:
        self.status_text.insert(END, msg + ("" if msg.endswith("\n") else "\n"))
        self.status_text.see(END)

    def _validate(self):
        key = self._selected_domain_key()
        domain = DOMAINS[key]
        try:
            step = float(self.step_var.get().replace(",", "."))
            transparent = float(self.transparent_var.get().replace(",", "."))
            date = dt.date.fromisoformat(self.date_var.get().strip())
        except Exception as exc:
            raise ValueError("Confira data, resolução e transparência. A data deve ser AAAA-MM-DD.") from exc
        nights = int(self.nights_var.get())
        start_hour = int(self.start_hour_var.get())
        end_hour = int(self.end_hour_var.get())
        if not 1 <= nights <= 7:
            raise ValueError("Número de noites precisa estar entre 1 e 7.")
        if step <= 0:
            raise ValueError("Resolução inválida.")
        if not 0 <= transparent <= 1:
            raise ValueError("Transparência precisa ficar entre 0 e 1.")
        return domain, step, date, nights, start_hour, end_hour, transparent

    def _start_generate(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Aguarde", "Uma geração já está em andamento.")
            return
        try:
            params = self._validate()
        except Exception as exc:
            messagebox.showerror("Configuração inválida", str(exc))
            return
        self.generate_button.config(state="disabled")
        self.listbox.delete(0, END)
        self.image_paths.clear()
        self._write_status("\n=== Nova geração ===")
        self.worker = threading.Thread(target=self._generate_worker, args=params, daemon=True)
        self.worker.start()

    def _generate_worker(self, domain, step, date, nights, start_hour, end_hour, transparent) -> None:
        try:
            def progress(msg: str) -> None:
                self.msg_queue.put(("log", msg))

            output_dir = Path(self.output_var.get()) / f"geada_{date:%Y%m%d}_{domain.key}_{step:g}deg"
            source = self.source_var.get()
            if source == "demo":
                progress("Gerando dados demo offline...")
                grid = make_demo_grid(domain, step, date, nights)
            else:
                grid = fetch_openmeteo_grid(domain, step, date, nights, progress=progress)

            progress("Calculando risco noturno...")
            results = compute_multiple_nights(grid, date, nights, start_hour=start_hour, end_hour=end_hour)
            progress("Gerando PNGs e CSVs...")
            paths = save_all_outputs(
                grid,
                results,
                output_dir,
                transparent_below=transparent,
                include_metric_maps=self.include_metrics_var.get(),
            )
            image_paths = [p for p in paths if p.suffix.lower() == ".png"]
            self.msg_queue.put(("done", output_dir, image_paths))
        except Exception as exc:  # noqa: BLE001
            self.msg_queue.put(("error", f"{exc}\n\n{traceback.format_exc()}"))

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.msg_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._write_status(item[1])
                elif kind == "done":
                    _, output_dir, image_paths = item
                    self._write_status(f"Concluído. Arquivos em: {output_dir}")
                    self.image_paths = list(image_paths)
                    self.listbox.delete(0, END)
                    for p in self.image_paths:
                        self.listbox.insert(END, p.name)
                    if self.image_paths:
                        self.listbox.selection_set(0)
                        self._show_image(self.image_paths[0])
                    self.generate_button.config(state="normal")
                    messagebox.showinfo("Concluído", f"Previsão gerada em:\n{output_dir}")
                elif kind == "error":
                    self._write_status("ERRO:\n" + item[1])
                    self.generate_button.config(state="normal")
                    messagebox.showerror("Erro", item[1].split("\n", 1)[0])
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def _on_select_image(self, _event=None) -> None:
        selection = self.listbox.curselection()
        if selection:
            self._show_image(self.image_paths[selection[0]])

    def _show_image(self, path: Path) -> None:
        if Image is None or ImageTk is None:
            self.preview_label.config(text=f"Imagem gerada:\n{path}\n\nInstale Pillow para pré-visualizar dentro do app.")
            return
        try:
            img = Image.open(path)
            max_w = max(400, self.preview_label.winfo_width() - 20)
            max_h = max(400, self.preview_label.winfo_height() - 20)
            img.thumbnail((max_w, max_h))
            self.current_photo = ImageTk.PhotoImage(img)
            self.preview_label.config(image=self.current_photo, text="")
        except Exception as exc:  # noqa: BLE001
            self.preview_label.config(text=f"Não foi possível abrir {path.name}: {exc}", image="")


def main() -> None:
    app = FrostApp()
    app.mainloop()


if __name__ == "__main__":
    main()
