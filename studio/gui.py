from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import asdict
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    ROOT_CLASS = TkinterDnD.Tk
except Exception:
    DND_FILES = None
    ROOT_CLASS = tk.Tk

from .models import PipelineOptions
from .platform.config import ApplicationConfig, ConfigurationError
from .mux import MEDIA_EXTENSIONS
from .pipeline import SUPPORTED_INPUTS, classify, process
from .utils import CancelledError, open_in_explorer


LANGUAGES = [
    ("Automatisch erkennen", "auto"),
    ("Deutsch", "de"),
    ("Englisch", "en"),
    ("Französisch", "fr"),
    ("Spanisch", "es"),
    ("Italienisch", "it"),
    ("Portugiesisch", "pt"),
    ("Niederländisch", "nl"),
    ("Polnisch", "pl"),
    ("Russisch", "ru"),
    ("Ukrainisch", "uk"),
    ("Türkisch", "tr"),
    ("Japanisch", "ja"),
    ("Koreanisch", "ko"),
    ("Chinesisch", "zh"),
]
LANG_LABEL_TO_CODE = dict(LANGUAGES)
LANG_CODE_TO_LABEL = {code: label for label, code in LANGUAGES}

QUALITY_FAIL_MODES = [
    ("Bei Prüfungsfehler stoppen", "stop"),
    ("Rohübersetzung verwenden", "use_raw"),
]
QUALITY_FAIL_LABEL_TO_CODE = dict(QUALITY_FAIL_MODES)
QUALITY_FAIL_CODE_TO_LABEL = {code: label for label, code in QUALITY_FAIL_MODES}


class StudioApp:
    def __init__(self) -> None:
        self.root = ROOT_CLASS()
        self.root.title("Transkript & Voiceover Studio")
        self.root.geometry("1220x820")
        self.root.minsize(980, 680)

        self.jobs: dict[str, dict] = {}
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.last_output: Path | None = None

        self._variables()
        self._style()
        self._build()
        self._load_settings()
        self.root.after(100, self._poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _variables(self) -> None:
        self.output_root = tk.StringVar()
        self.do_transcribe = tk.BooleanVar(value=True)
        self.do_translate = tk.BooleanVar(value=True)
        self.do_voiceover = tk.BooleanVar(value=True)
        self.do_mux = tk.BooleanVar(value=False)

        self.whisper_model = tk.StringVar(value="small")
        self.whisper_language = tk.StringVar(value="Automatisch erkennen")
        self.device = tk.StringVar(value="auto")
        self.compute_type = tk.StringVar(value="auto")
        self.beam_size = tk.IntVar(value=5)
        self.vad_filter = tk.BooleanVar(value=True)
        self.diarization = tk.BooleanVar(value=False)
        self.hf_token = tk.StringVar()

        self.srt_language = tk.StringVar(value="Automatisch erkennen")
        self.translation_engine = tk.StringVar(value="google")
        self.ollama_url = tk.StringVar(value="http://127.0.0.1:11434")
        self.ollama_model = tk.StringVar(value="qwen3:8b")

        self.quality_check = tk.BooleanVar(value=True)
        self.quality_model = tk.StringVar(value="qwen3:8b")
        self.quality_batch_size = tk.IntVar(value=10)
        self.quality_max_chars = tk.IntVar(value=5200)
        self.quality_context_before = tk.IntVar(value=2)
        self.quality_context_after = tk.IntVar(value=2)
        self.quality_fail_mode = tk.StringVar(value="Bei Prüfungsfehler stoppen")

        self.voice_map = tk.StringVar()
        self.voice_rate = tk.StringVar(value="+0%")
        self.voice_volume = tk.StringVar(value="+0%")
        self.voice_pitch = tk.StringVar(value="+0Hz")
        self.bitrate = tk.StringVar(value="192k")
        self.sample_rate = tk.IntVar(value=24000)
        self.max_compress = tk.DoubleVar(value=0.5)
        self.gap_ms = tk.IntVar(value=40)
        self.skip_non_speech = tk.BooleanVar(value=True)
        self.keep_parts = tk.BooleanVar(value=False)
        self.keep_raw_tts = tk.BooleanVar(value=False)

        self.mux_mode = tk.StringVar(value="replace")
        self.original_volume = tk.DoubleVar(value=0.22)
        self.voiceover_volume = tk.DoubleVar(value=1.0)
        self.keep_temp = tk.BooleanVar(value=False)

        self.status = tk.StringVar(value="Bereit")
        self.progress_value = tk.DoubleVar(value=0.0)

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Heading.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Sub.TLabel", foreground="#555555")
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", rowheight=25)

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="Transkript & Voiceover Studio",
            style="Heading.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Einstieg wahlweise mit Video/Audio, fremdsprachiger SRT "
                "oder deutscher SRT. Jede Bearbeitungsstufe ist einzeln startbar."
            ),
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)

        self.workflow_tab = ttk.Frame(self.notebook, padding=10)
        self.transcription_tab = ttk.Frame(self.notebook, padding=10)
        self.translation_tab = ttk.Frame(self.notebook, padding=10)
        self.voice_tab = ttk.Frame(self.notebook, padding=10)
        self.video_tab = ttk.Frame(self.notebook, padding=10)
        self.log_tab = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.workflow_tab, text="Ablauf")
        self.notebook.add(self.transcription_tab, text="Transkription")
        self.notebook.add(self.translation_tab, text="Übersetzung")
        self.notebook.add(self.voice_tab, text="Voiceover")
        self.notebook.add(self.video_tab, text="Videoausgabe")
        self.notebook.add(self.log_tab, text="Protokoll")

        self._build_workflow()
        self._build_transcription()
        self._build_translation()
        self._build_voice()
        self._build_video()
        self._build_log()

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Progressbar(
            footer,
            variable=self.progress_value,
            maximum=100,
        ).pack(side="left", fill="x", expand=True)
        ttk.Label(footer, textvariable=self.status, width=42).pack(
            side="left", padx=(10, 0)
        )

    def _build_workflow(self) -> None:
        tab = self.workflow_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        controls = ttk.Frame(tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(
            controls, text="Video/Audio hinzufügen", command=self._add_media
        ).pack(side="left")
        ttk.Button(
            controls, text="SRT hinzufügen", command=self._add_srt
        ).pack(side="left", padx=5)
        ttk.Button(
            controls,
            text="Begleitvideo zuordnen",
            command=self._assign_companion,
        ).pack(side="left", padx=5)
        ttk.Button(
            controls, text="Entfernen", command=self._remove_selected
        ).pack(side="left", padx=5)
        ttk.Button(
            controls, text="Liste leeren", command=self._clear_jobs
        ).pack(side="left")

        columns = ("input", "type", "companion", "status")
        self.tree = ttk.Treeview(
            tab,
            columns=columns,
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("input", text="Eingabedatei")
        self.tree.heading("type", text="Einstieg")
        self.tree.heading("companion", text="Begleitvideo für SRT")
        self.tree.heading("status", text="Status")
        self.tree.column("input", width=460)
        self.tree.column("type", width=90, anchor="center")
        self.tree.column("companion", width=330)
        self.tree.column("status", width=180)
        self.tree.grid(row=1, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        if DND_FILES:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind("<<Drop>>", self._on_drop)

        settings = ttk.LabelFrame(tab, text="Aktive Bearbeitungsstufen", padding=8)
        settings.grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Checkbutton(
            settings, text="1. Transkription (nur bei Video/Audio)",
            variable=self.do_transcribe
        ).grid(row=0, column=0, sticky="w", padx=5)
        ttk.Checkbutton(
            settings, text="2. Falls nötig nach Deutsch übersetzen",
            variable=self.do_translate
        ).grid(row=0, column=1, sticky="w", padx=12)
        ttk.Checkbutton(
            settings, text="3. Voiceover erzeugen",
            variable=self.do_voiceover
        ).grid(row=0, column=2, sticky="w", padx=12)
        ttk.Checkbutton(
            settings, text="4. Voiceover mit Video verbinden",
            variable=self.do_mux
        ).grid(row=0, column=3, sticky="w", padx=12)

        output = ttk.Frame(tab)
        output.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        output.columnconfigure(1, weight=1)
        ttk.Label(output, text="Ausgabe-Stammordner (leer = neben Eingabe):").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(output, textvariable=self.output_root).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Button(output, text="Auswählen", command=self._choose_output).grid(
            row=0, column=2
        )

        actions = ttk.Frame(tab)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Button(
            actions,
            text="Gesamten Ablauf starten",
            style="Accent.TButton",
            command=lambda: self._start("full"),
        ).pack(side="left")
        ttk.Button(
            actions,
            text="Nur transkribieren",
            command=lambda: self._start("transcribe"),
        ).pack(side="left", padx=5)
        ttk.Button(
            actions,
            text="Nur SRT übersetzen",
            command=lambda: self._start("translate"),
        ).pack(side="left", padx=5)
        ttk.Button(
            actions,
            text="Nur Voiceover erzeugen",
            command=lambda: self._start("voiceover"),
        ).pack(side="left", padx=5)
        ttk.Button(
            actions,
            text="Abbrechen",
            command=self._cancel,
        ).pack(side="left", padx=5)
        ttk.Button(
            actions,
            text="Letzten Ausgabeordner öffnen",
            command=self._open_last_output,
        ).pack(side="right")

    def _grid_entry(
        self,
        parent,
        row: int,
        label: str,
        variable,
        *,
        values=None,
        width=28,
        show=None,
    ):
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=4
        )
        if values:
            widget = ttk.Combobox(
                parent,
                textvariable=variable,
                values=values,
                state="readonly",
                width=width,
            )
        else:
            widget = ttk.Entry(
                parent,
                textvariable=variable,
                width=width,
                show=show,
            )
        widget.grid(row=row, column=1, sticky="w", pady=4)
        return widget

    def _build_transcription(self) -> None:
        tab = self.transcription_tab
        tab.columnconfigure(2, weight=1)
        ttk.Label(
            tab,
            text="Diese Einstellungen gelten nur beim Einstieg mit Video oder Audio.",
            style="Sub.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._grid_entry(
            tab, 1, "Whisper-Modell", self.whisper_model,
            values=["tiny", "base", "small", "medium", "large-v3", "turbo"]
        )
        self._grid_entry(
            tab, 2, "Sprache", self.whisper_language,
            values=[label for label, _ in LANGUAGES]
        )
        self._grid_entry(
            tab, 3, "Gerät", self.device,
            values=["auto", "cuda", "cpu"]
        )
        self._grid_entry(
            tab, 4, "Rechentyp", self.compute_type,
            values=["auto", "float16", "int8_float16", "int8", "float32"]
        )
        self._grid_entry(tab, 5, "Beam Size", self.beam_size)
        ttk.Checkbutton(
            tab, text="Sprachaktivitätserkennung (VAD)",
            variable=self.vad_filter
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=5)
        ttk.Separator(tab).grid(row=7, column=0, columnspan=3, sticky="ew", pady=10)
        ttk.Checkbutton(
            tab,
            text="Sprecher automatisch trennen (pyannote)",
            variable=self.diarization,
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=5)
        self._grid_entry(
            tab, 9, "Hugging-Face-Token", self.hf_token,
            width=55, show="•"
        )
        ttk.Label(
            tab,
            text=(
                "Für pyannote muss der Zugriff auf "
                "'pyannote/speaker-diarization-community-1' freigeschaltet sein."
            ),
            style="Sub.TLabel",
        ).grid(row=10, column=0, columnspan=3, sticky="w", pady=4)

    def _build_translation(self) -> None:
        tab = self.translation_tab
        ttk.Label(
            tab,
            text=(
                "Bei deutscher SRT wird diese Stufe automatisch übersprungen. "
                "Bei fremdsprachiger SRT beginnt der Ablauf direkt hier."
            ),
            style="Sub.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._grid_entry(
            tab, 1, "Sprache einer hinzugefügten SRT", self.srt_language,
            values=[label for label, _ in LANGUAGES], width=30
        )
        self._grid_entry(
            tab, 2, "Übersetzungs-Engine", self.translation_engine,
            values=["google", "ollama", "none"]
        )
        self._grid_entry(tab, 3, "Ollama-Adresse", self.ollama_url, width=45)
        self._grid_entry(tab, 4, "Ollama-Modell für Übersetzung", self.ollama_model, width=30)
        ttk.Label(
            tab,
            text=(
                "Google benötigt Internet. Ollama übersetzt lokal und muss bereits "
                "laufen. Sprecherlabels und SRT-Zeitstempel bleiben erhalten."
            ),
            style="Sub.TLabel",
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 10))

        ttk.Separator(tab).grid(row=6, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Checkbutton(
            tab,
            text="Übersetzung vor der Vertonung durch KI sprachlich prüfen",
            variable=self.quality_check,
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=5)
        self._grid_entry(
            tab, 8, "Ollama-Modell für Sprachprüfung", self.quality_model, width=30
        )
        self._grid_entry(tab, 9, "Blöcke pro Prüfpaket", self.quality_batch_size)
        self._grid_entry(tab, 10, "Maximale Zeichen pro Paket", self.quality_max_chars)
        self._grid_entry(tab, 11, "Kontextblöcke davor", self.quality_context_before)
        self._grid_entry(tab, 12, "Kontextblöcke danach", self.quality_context_after)
        self._grid_entry(
            tab,
            13,
            "Bei Fehler",
            self.quality_fail_mode,
            values=[label for label, _ in QUALITY_FAIL_MODES],
            width=32,
        )
        ttk.Label(
            tab,
            text=(
                "Die Prüfung vergleicht Original und Rohübersetzung über mehrere "
                "Untertitelblöcke. Sie korrigiert Sinn, Grammatik, Ausdruck und "
                "Verständlichkeit. Die Rohfassung bleibt als *_de_roh.srt erhalten."
            ),
            style="Sub.TLabel",
            wraplength=900,
        ).grid(row=14, column=0, columnspan=3, sticky="w", pady=8)

    def _build_voice(self) -> None:
        tab = self.voice_tab
        ttk.Label(
            tab,
            text=(
                "Eine deutsche SRT kann direkt auf dieser Stufe gestartet werden. "
                "Ohne Sprecherlabels wird SPEAKER_00 verwendet."
            ),
            style="Sub.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._grid_entry(
            tab, 1, "Stimmenzuordnung", self.voice_map, width=75
        )
        ttk.Label(
            tab,
            text=(
                "Beispiel: SPEAKER_00=de-DE-ConradNeural, "
                "SPEAKER_01=de-DE-KatjaNeural"
            ),
            style="Sub.TLabel",
        ).grid(row=2, column=0, columnspan=3, sticky="w")
        self._grid_entry(tab, 3, "Tempo", self.voice_rate)
        self._grid_entry(tab, 4, "Lautstärke", self.voice_volume)
        self._grid_entry(tab, 5, "Tonhöhe", self.voice_pitch)
        self._grid_entry(
            tab, 6, "MP3-Bitrate", self.bitrate,
            values=["128k", "160k", "192k", "256k", "320k"]
        )
        self._grid_entry(tab, 7, "Samplerate", self.sample_rate)
        self._grid_entry(
            tab, 8, "Max. Verkürzung pro Block (Sek.)", self.max_compress
        )
        self._grid_entry(tab, 9, "Abstand zwischen Blöcken (ms)", self.gap_ms)
        ttk.Checkbutton(
            tab,
            text="Musik- und Geräuschuntertitel nicht vorlesen",
            variable=self.skip_non_speech,
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=5)
        ttk.Checkbutton(
            tab,
            text="Temporäre WAV-Teile behalten",
            variable=self.keep_parts,
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=5)
        ttk.Checkbutton(
            tab,
            text="Unbearbeitete Edge-TTS-MP3s behalten",
            variable=self.keep_raw_tts,
        ).grid(row=12, column=0, columnspan=2, sticky="w", pady=5)

    def _build_video(self) -> None:
        tab = self.video_tab
        ttk.Label(
            tab,
            text=(
                "Beim Video-Einstieg wird die Originaldatei verwendet. "
                "Bei SRT-Einstieg kann ein Begleitvideo zugeordnet oder anhand "
                "des Dateinamens automatisch gefunden werden."
            ),
            style="Sub.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._grid_entry(
            tab, 1, "Tonmodus", self.mux_mode,
            values=["replace", "mix"]
        )
        self._grid_entry(
            tab, 2, "Originalton-Lautstärke bei mix", self.original_volume
        )
        self._grid_entry(
            tab, 3, "Voiceover-Lautstärke bei mix", self.voiceover_volume
        )
        ttk.Checkbutton(
            tab,
            text="Arbeitsdateien behalten",
            variable=self.keep_temp,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=5)
        ttk.Label(
            tab,
            text=(
                "Ausgabe ist MKV. Das Video wird ohne Qualitätsverlust kopiert; "
                "nur die neue Tonspur wird als AAC kodiert."
            ),
            style="Sub.TLabel",
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=8)

    def _build_log(self) -> None:
        self.log_text = tk.Text(
            self.log_tab,
            wrap="word",
            font=("Consolas", 9),
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)
        buttons = ttk.Frame(self.log_tab)
        buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(
            buttons, text="Protokoll leeren", command=self._clear_log
        ).pack(side="left")
        ttk.Button(
            buttons, text="Protokoll speichern", command=self._save_log
        ).pack(side="left", padx=5)

    def _add_paths(self, paths: list[str]) -> None:
        for raw in paths:
            path = Path(raw).expanduser().resolve()
            if not path.exists() or path.suffix.lower() not in SUPPORTED_INPUTS:
                continue
            if any(job["source"] == path for job in self.jobs.values()):
                continue
            iid = self.tree.insert(
                "",
                "end",
                values=(str(path), classify(path), "", "Bereit"),
            )
            self.jobs[iid] = {
                "source": path,
                "companion": None,
                "status": "Bereit",
            }

    def _add_media(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Video- oder Audiodateien auswählen",
            filetypes=[
                ("Medien", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.wma"),
                ("Alle Dateien", "*.*"),
            ],
        )
        self._add_paths(list(paths))

    def _add_srt(self) -> None:
        paths = filedialog.askopenfilenames(
            title="SRT-Dateien auswählen",
            filetypes=[("SubRip-Untertitel", "*.srt"), ("Alle Dateien", "*.*")],
        )
        self._add_paths(list(paths))

    def _on_drop(self, event) -> None:
        try:
            paths = list(self.root.tk.splitlist(event.data))
        except Exception:
            paths = [event.data]
        self._add_paths(paths)

    def _assign_companion(self) -> None:
        selected = self.tree.selection()
        srt_items = [
            iid for iid in selected
            if self.jobs[iid]["source"].suffix.lower() == ".srt"
        ]
        if not srt_items:
            messagebox.showinfo(
                "Begleitvideo",
                "Wähle mindestens eine SRT-Zeile aus.",
            )
            return
        path = filedialog.askopenfilename(
            title="MP4/MKV als Begleitvideo auswählen",
            filetypes=[
                ("Video", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v"),
                ("Alle Dateien", "*.*"),
            ],
        )
        if not path:
            return
        media = Path(path).resolve()
        for iid in srt_items:
            self.jobs[iid]["companion"] = media
            values = list(self.tree.item(iid, "values"))
            values[2] = str(media)
            self.tree.item(iid, values=values)

    def _remove_selected(self) -> None:
        for iid in self.tree.selection():
            self.jobs.pop(iid, None)
            self.tree.delete(iid)

    def _clear_jobs(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        for iid in list(self.jobs):
            self.tree.delete(iid)
        self.jobs.clear()

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(title="Ausgabe-Stammordner")
        if path:
            self.output_root.set(path)

    def _selected_jobs(self) -> list[tuple[str, dict]]:
        selected = list(self.tree.selection())
        if not selected:
            selected = list(self.tree.get_children())
        return [(iid, self.jobs[iid]) for iid in selected if iid in self.jobs]

    def _options(self) -> PipelineOptions:
        return PipelineOptions(
            output_root=self.output_root.get().strip(),
            do_transcribe=self.do_transcribe.get(),
            do_translate=self.do_translate.get(),
            do_voiceover=self.do_voiceover.get(),
            do_mux=self.do_mux.get(),
            whisper_model=self.whisper_model.get().strip(),
            whisper_language=LANG_LABEL_TO_CODE.get(
                self.whisper_language.get(), "auto"
            ),
            device=self.device.get(),
            compute_type=self.compute_type.get(),
            beam_size=max(1, int(self.beam_size.get())),
            vad_filter=self.vad_filter.get(),
            diarization=self.diarization.get(),
            hf_token=self.hf_token.get().strip(),
            srt_language=LANG_LABEL_TO_CODE.get(
                self.srt_language.get(), "auto"
            ),
            translation_engine=self.translation_engine.get(),
            ollama_url=self.ollama_url.get().strip(),
            ollama_model=self.ollama_model.get().strip(),
            quality_check=self.quality_check.get(),
            quality_model=self.quality_model.get().strip(),
            quality_batch_size=max(1, int(self.quality_batch_size.get())),
            quality_max_chars=max(1000, int(self.quality_max_chars.get())),
            quality_context_before=max(0, int(self.quality_context_before.get())),
            quality_context_after=max(0, int(self.quality_context_after.get())),
            quality_fail_mode=QUALITY_FAIL_LABEL_TO_CODE.get(
                self.quality_fail_mode.get(), "stop"
            ),
            voice_map=self.voice_map.get().strip(),
            voice_rate=self.voice_rate.get().strip(),
            voice_volume=self.voice_volume.get().strip(),
            voice_pitch=self.voice_pitch.get().strip(),
            bitrate=self.bitrate.get(),
            sample_rate=int(self.sample_rate.get()),
            max_compress_seconds=float(self.max_compress.get()),
            gap_ms=int(self.gap_ms.get()),
            skip_non_speech=self.skip_non_speech.get(),
            keep_parts=self.keep_parts.get(),
            keep_raw_tts=self.keep_raw_tts.get(),
            mux_mode=self.mux_mode.get(),
            original_volume=float(self.original_volume.get()),
            voiceover_volume=float(self.voiceover_volume.get()),
            keep_temp=self.keep_temp.get(),
        )

    def _start(self, mode: str) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Läuft bereits", "Es läuft bereits ein Auftrag.")
            return

        jobs = self._selected_jobs()
        if not jobs:
            messagebox.showwarning("Keine Eingabe", "Füge zuerst Dateien hinzu.")
            return

        options = self._options()
        if mode == "transcribe":
            options.do_transcribe = True
            options.do_translate = False
            options.do_voiceover = False
            options.do_mux = False
        elif mode == "translate":
            options.do_transcribe = False
            options.do_translate = True
            options.do_voiceover = False
            options.do_mux = False
        elif mode == "voiceover":
            options.do_transcribe = False
            options.do_translate = False
            options.do_voiceover = True
            options.do_mux = False

        self.cancel_event.clear()
        self.progress_value.set(0)
        self.status.set("Starte …")
        self._save_settings()
        self.worker = threading.Thread(
            target=self._worker,
            args=(jobs, options, mode),
            daemon=True,
        )
        self.worker.start()

    def _worker(self, jobs, options, mode) -> None:
        total = len(jobs)
        failures = 0
        for job_index, (iid, job) in enumerate(jobs, 1):
            if self.cancel_event.is_set():
                break
            source = job["source"]
            self.events.put(("status_row", iid, "Läuft"))
            self.events.put(
                ("log", f"\n{'=' * 78}\n[{job_index}/{total}] {source}\n")
            )

            def log(message: str) -> None:
                self.events.put(("log", message))

            def progress(value: float, message: str) -> None:
                overall = (
                    (job_index - 1) + max(0.0, min(value, 1.0))
                ) / total
                self.events.put(
                    ("progress", overall * 100.0, f"{job_index}/{total}: {message}")
                )

            try:
                result = process(
                    source,
                    job.get("companion"),
                    options,
                    mode=mode,
                    log=log,
                    progress=progress,
                    cancel_event=self.cancel_event,
                )
                self.events.put(("status_row", iid, "Fertig"))
                self.events.put(("last_output", str(result.output_dir)))
                self.events.put(
                    ("log", f"FERTIG: {result.output_dir}")
                )
            except CancelledError as exc:
                self.events.put(("status_row", iid, "Abgebrochen"))
                self.events.put(("log", str(exc)))
                break
            except Exception as exc:
                failures += 1
                self.events.put(("status_row", iid, "Fehler"))
                self.events.put(("log", f"FEHLER: {exc}"))
                self.events.put(("log", traceback.format_exc()))

        self.events.put(("finished", failures, self.cancel_event.is_set()))

    def _cancel(self) -> None:
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.status.set("Abbruch wird ausgeführt …")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._append_log(event[1])
                elif kind == "progress":
                    self.progress_value.set(event[1])
                    self.status.set(event[2])
                elif kind == "status_row":
                    iid, status = event[1], event[2]
                    if iid in self.jobs:
                        values = list(self.tree.item(iid, "values"))
                        values[3] = status
                        self.tree.item(iid, values=values)
                elif kind == "last_output":
                    self.last_output = Path(event[1])
                elif kind == "finished":
                    failures, cancelled = event[1], event[2]
                    if cancelled:
                        self.status.set("Abgebrochen")
                    elif failures:
                        self.status.set(f"Fertig mit {failures} Fehler(n)")
                    else:
                        self.status.set("Alle Aufträge fertig")
                        self.progress_value.set(100)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _save_log(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Protokoll speichern",
            defaultextension=".txt",
            filetypes=[("Textdatei", "*.txt")],
        )
        if path:
            Path(path).write_text(
                self.log_text.get("1.0", "end-1c"),
                encoding="utf-8",
            )

    def _open_last_output(self) -> None:
        if self.last_output and self.last_output.exists():
            open_in_explorer(self.last_output)
        else:
            messagebox.showinfo(
                "Ausgabe",
                "Es wurde noch kein Ausgabeordner erzeugt.",
            )

    def _settings_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "settings.json"

    def _save_settings(self) -> None:
        options = asdict(self._options())
        options.pop("hf_token", None)
        options["whisper_language_label"] = self.whisper_language.get()
        options["srt_language_label"] = self.srt_language.get()
        try:
            current = ApplicationConfig.load(self._settings_path())
            values = dict(current.values)
            values.update(options)
            ApplicationConfig(values, self._settings_path()).save()
        except ConfigurationError:
            pass

    def _load_settings(self) -> None:
        path = self._settings_path()
        if not path.exists():
            return
        try:
            data = ApplicationConfig.load(path).values
        except ConfigurationError:
            return

        mapping = {
            "output_root": self.output_root,
            "do_transcribe": self.do_transcribe,
            "do_translate": self.do_translate,
            "do_voiceover": self.do_voiceover,
            "do_mux": self.do_mux,
            "whisper_model": self.whisper_model,
            "device": self.device,
            "compute_type": self.compute_type,
            "beam_size": self.beam_size,
            "vad_filter": self.vad_filter,
            "diarization": self.diarization,
            "translation_engine": self.translation_engine,
            "ollama_url": self.ollama_url,
            "ollama_model": self.ollama_model,
            "quality_check": self.quality_check,
            "quality_model": self.quality_model,
            "quality_batch_size": self.quality_batch_size,
            "quality_max_chars": self.quality_max_chars,
            "quality_context_before": self.quality_context_before,
            "quality_context_after": self.quality_context_after,
            "voice_map": self.voice_map,
            "voice_rate": self.voice_rate,
            "voice_volume": self.voice_volume,
            "voice_pitch": self.voice_pitch,
            "bitrate": self.bitrate,
            "sample_rate": self.sample_rate,
            "max_compress_seconds": self.max_compress,
            "gap_ms": self.gap_ms,
            "skip_non_speech": self.skip_non_speech,
            "keep_parts": self.keep_parts,
            "keep_raw_tts": self.keep_raw_tts,
            "mux_mode": self.mux_mode,
            "original_volume": self.original_volume,
            "voiceover_volume": self.voiceover_volume,
            "keep_temp": self.keep_temp,
        }
        for key, variable in mapping.items():
            if key in data:
                try:
                    variable.set(data[key])
                except Exception:
                    pass
        if "whisper_language_label" in data:
            self.whisper_language.set(data["whisper_language_label"])
        if "srt_language_label" in data:
            self.srt_language.set(data["srt_language_label"])
        if "quality_fail_mode" in data:
            self.quality_fail_mode.set(
                QUALITY_FAIL_CODE_TO_LABEL.get(
                    data["quality_fail_mode"], "Bei Prüfungsfehler stoppen"
                )
            )

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                "Beenden",
                "Ein Auftrag läuft noch. Wirklich abbrechen und schließen?",
            ):
                return
            self.cancel_event.set()
        self._save_settings()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    StudioApp().run()
