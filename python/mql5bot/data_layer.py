"""mql5bot.data_layer — production research data layer (mission
Phase 6).

Every dataset carries its full identity (instrument, timeframe,
timezone, source, source/download timestamps, content SHA-256, schema
version, quality status) and is AUDITED before use:

* duplicate timestamps
* timestamp disorder
* impossible OHLC (high < max(open, close), low > min(open, close))
* non-positive prices
* session gaps (> 3× the median bar spacing)
* weekend/session artifacts (reported, never repaired)

Cleaning is EXPLICIT: :func:`clean_ohlcv` returns the repaired frame
TOGETHER with a change log — data is never silently repaired.  Every
research run can name its exact dataset content hash (the same digest
the RunManifest records).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

DATA_SCHEMA_VERSION = "1"
REQUIRED_COLUMNS = ("open", "high", "low", "close")


# ---- identity --------------------------------------------------------------


@dataclass
class DatasetIdentity:
    """Immutable provenance of one dataset version."""

    instrument: str
    timeframe: str
    timezone_name: str
    source: str
    source_timestamp: str        # provider's last-bar timestamp (UTC ISO)
    download_timestamp: str
    sha256: str
    bars: int
    schema_version: str = DATA_SCHEMA_VERSION
    quality: str = "UNKNOWN"     # OK | WARNINGS | CORRUPT
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def content_digest(frame: pd.DataFrame) -> str:
    """Deterministic content hash of an OHLCV frame (canonical JSON of
    values; index included as ISO timestamps)."""
    payload = {
        "columns": list(frame.columns),
        "index": [str(i) for i in frame.index],
        "values": np.round(frame.to_numpy(dtype=float), 10).tolist(),
    }
    blob = json.dumps(payload, sort_keys=True,
                      separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


# ---- audit -----------------------------------------------------------------


def audit_ohlcv(df: pd.DataFrame, *, max_gap_factor: float = 3.0
                ) -> dict:
    """Audit one OHLCV frame.  Returns
    ``{"identity-ish": ..., "quality": OK|WARNINGS|CORRUPT,
    "findings": [{type, detail}...]}``.  Never mutates the input and
    never repairs anything."""
    findings: list[dict] = []
    if len(df) == 0:
        return {"quality": "CORRUPT", "bars": 0,
                "findings": [{"type": "empty", "detail": "no bars"}]}

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return {"quality": "CORRUPT", "bars": len(df),
                "findings": [{"type": "missing_columns",
                              "detail": missing}]}

    if df.index.has_duplicates:
        dupes = df.index[df.index.duplicated()].unique()
        findings.append({"type": "duplicate_timestamp",
                         "detail": [str(d) for d in dupes[:5]],
                         "count": int(df.index.duplicated().sum())})
    if not df.index.is_monotonic_increasing:
        findings.append({"type": "timestamp_disorder",
                         "detail": "index not ascending"})

    px = df[["open", "high", "low", "close"]].to_numpy(dtype=float)
    bad = ~np.isfinite(px)
    if bad.any():
        findings.append({"type": "nonfinite_price",
                         "count": int(bad.sum())})
    nonpos = (px[np.isfinite(px)] <= 0.0)
    if nonpos.any():
        findings.append({"type": "nonpositive_price",
                         "count": int(nonpos.sum())})
    imposs = ((df["high"] < df[["open", "close"]].max(axis=1))
              | (df["low"] > df[["open", "close"]].min(axis=1))
              | (df["high"] < df["low"]))
    if imposs.any():
        findings.append({"type": "impossible_ohlc",
                         "count": int(imposs.sum()),
                         "detail": [str(i) for i in
                                    df.index[imposs][:5]]})

    if len(df) >= 3:
        gaps = np.diff(df.index.view(np.int64))
        median_gap = float(np.median(gaps))
        if median_gap > 0:
            thresh = median_gap * max_gap_factor
            big = gaps > thresh
            if big.any():
                findings.append({
                    "type": "gap", "count": int(big.sum()),
                    "detail": f"{int(big.sum())} gaps > "
                              f"{max_gap_factor}x median spacing",
                    "largest_bars": int(gaps.max() / median_gap)})

    quality = "OK"
    if findings:
        hard = {"duplicate_timestamp", "timestamp_disorder",
                "impossible_ohlc", "nonpositive_price", "nonfinite_price",
                "missing_columns", "empty"}
        quality = "CORRUPT" if any(f["type"] in hard for f in findings) \
            else "WARNINGS"
    return {"quality": quality, "bars": len(df), "findings": findings}


def clean_ohlcv(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """EXPLICIT cleaning: returns (frame, change_log).  Only safe,
    lossless-or-documented operations are performed: sort by timestamp,
    drop duplicate timestamps (keep first), drop bars with non-positive
    or non-finite prices, clamp impossible high/low into consistency.
    Every change is logged — a caller can always reconstruct what was
    removed.  Gaps are REPORTED by audit, never filled."""
    changes: list[dict] = []
    out = df.copy()

    if not out.index.is_monotonic_increasing:
        out = out.sort_index()
        changes.append({"op": "sort_index", "rows": len(out)})
    if out.index.has_duplicates:
        n = int(out.index.duplicated().sum())
        out = out[~out.index.duplicated(keep="first")]
        changes.append({"op": "drop_duplicate_timestamps", "rows": n})
    px = out[["open", "high", "low", "close"]].to_numpy(dtype=float)
    bad = ~np.isfinite(px).all(axis=1) | (px <= 0.0).any(axis=1)
    if bad.any():
        n = int(bad.sum())
        out = out[~bad]
        changes.append({"op": "drop_invalid_price_bars", "rows": n})
    imposs = (out["high"] < out[["open", "close"]].max(axis=1)) \
        | (out["low"] > out[["open", "close"]].min(axis=1))
    if imposs.any():
        n = int(imposs.sum())
        hi = out[["open", "close"]].max(axis=1)
        lo = out[["open", "close"]].min(axis=1)
        out.loc[imposs, "high"] = np.maximum(out.loc[imposs, "high"], hi)
        out.loc[imposs, "low"] = np.minimum(out.loc[imposs, "low"], lo)
        changes.append({"op": "clamp_impossible_high_low", "rows": n})
    return out, changes


def register_dataset(frame: pd.DataFrame, *, instrument: str,
                     timeframe: str, tz: str, source: str,
                     source_timestamp: str | None = None,
                     download_timestamp: str | None = None) -> dict:
    """Audit + identity a dataset.  Returns the registration record
    (identity + audit).  CORRUPT datasets are returned with
    quality=CORRUPT — the caller must refuse to backtest them."""
    audit = audit_ohlcv(frame)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    identity = DatasetIdentity(
        instrument=instrument, timeframe=timeframe, timezone_name=tz,
        source=source,
        source_timestamp=source_timestamp
        or str(frame.index[-1]),
        download_timestamp=download_timestamp or now,
        sha256=content_digest(frame), bars=len(frame),
        quality=audit["quality"], notes=[f["type"] for f in
                                         audit["findings"]])
    return {"identity": identity.to_dict(), "audit": audit}


# ---- committed REAL data ----------------------------------------------------


def load_real_vix(repo_root: Path) -> tuple[pd.DataFrame, str]:
    """Load the committed REAL CBOE VIX daily series (DataHub mirror)
    and its content digest.  Raises if the provenance manifest digest
    does not match the file bytes."""
    path = Path(repo_root) / "tests/data/real/vix_daily.csv"
    blob = path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    manifest = json.loads(
        (path.parent / "manifest.json").read_text())
    recorded = manifest["sources"]["vix_daily"]["sha256"]
    if digest != recorded:
        raise ValueError(
            f"dataset digest mismatch: file {digest[:12]} vs manifest "
            f"{recorded[:12]} — refusing to use unverified data")
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")[["open", "high", "low", "close"]] \
        .astype(float).sort_index()
    return df, digest


# ---- RAW / CLEAN / DERIVED store (immutable lineage) ------------------------


class DatasetStore:
    """Three-layer dataset store with immutable lineage.

    * ``raw/``     — bytes exactly as downloaded; written once, never
                     rewritten (refuses overwrite), sha256 of file bytes is
                     the identity anchor.
    * ``clean/``   — raw + EXPLICIT change log (``clean_ohlcv``); gaps are
                     never filled; every clean record names its raw parent.
    * ``derived/`` — computed from a clean parent (resampling, features);
                     names parent sha + transform, so any backtest consuming
                     a derived frame traces to raw bytes.

    Every layer exposes a :meth:`ref` giving BOTH digests: the content
    sha256 (storage identity) and the manifest digest
    (``optimizer._dataset_digest``) that :class:`pipeline.RunManifest`
    records — the seam that lets any backtest name its exact dataset.
    """

    LAYERS = ("raw", "clean", "derived")

    def __init__(self, root: Path):
        self.root = Path(root)
        for layer in self.LAYERS:
            (self.root / layer).mkdir(parents=True, exist_ok=True)

    # -- raw ---------------------------------------------------------------

    def save_raw(self, frame: pd.DataFrame, name: str, *, instrument: str,
                 timeframe: str, tz: str, source: str,
                 source_timestamp: str | None = None) -> dict:
        path = self.root / "raw" / f"{name}.csv"
        if path.exists():
            raise FileExistsError(
                f"raw layer is immutable: {name} already exists "
                f"(re-download under a new name)")
        frame.to_csv(path)
        blob = path.read_bytes()
        reg = register_dataset(frame, instrument=instrument,
                               timeframe=timeframe, tz=tz, source=source,
                               source_timestamp=source_timestamp)
        reg["layer"] = "raw"
        reg["file"] = str(path)
        reg["file_sha256"] = hashlib.sha256(blob).hexdigest()
        content, manifest = self._bind_digests(path)
        reg["identity"]["sha256"] = content
        reg["manifest_digest"] = manifest
        self._write_meta("raw", name, reg)
        return reg

    # -- clean -------------------------------------------------------------

    def promote_clean(self, raw_name: str, *, note: str = "") -> dict:
        raw_meta = self._read_meta("raw", raw_name)
        df = pd.read_csv(self.root / "raw" / f"{raw_name}.csv",
                         index_col=0, parse_dates=True)
        before = audit_ohlcv(df)
        if before["quality"] == "CORRUPT" and not self._cleanable(before):
            raise ValueError(
                f"{raw_name}: raw dataset CORRUPT with uncleanable findings "
                f"{[f['type'] for f in before['findings']]} — refusing to "
                f"promote; fix at the source")
        cleaned, change_log = clean_ohlcv(df)
        after = audit_ohlcv(cleaned)
        name = f"{raw_name}_clean"
        path = self.root / "clean" / f"{name}.csv"
        cleaned.to_csv(path)
        reg = register_dataset(cleaned, instrument=raw_meta["identity"]["instrument"],
                               timeframe=raw_meta["identity"]["timeframe"],
                               tz=raw_meta["identity"]["timezone_name"],
                               source=raw_meta["identity"]["source"],
                               source_timestamp=raw_meta["identity"]["source_timestamp"])
        reg["layer"] = "clean"
        reg["file"] = str(path)
        reg["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        content, manifest = self._bind_digests(path)
        reg["identity"]["sha256"] = content
        reg["manifest_digest"] = manifest
        reg["parent"] = {"layer": "raw", "name": raw_name,
                         "file_sha256": raw_meta["file_sha256"]}
        reg["change_log"] = change_log
        reg["audit_raw"] = before
        reg["audit_clean"] = after
        if note:
            reg["note"] = note
        self._write_meta("clean", name, reg)
        return reg

    # -- derived -----------------------------------------------------------

    def add_derived(self, clean_name: str, transform: str,
                    build) -> dict:
        """``build(clean_frame) -> DataFrame``; the transform name and the
        parent's sha are recorded so derived data is reproducible."""
        clean_meta = self._read_meta("clean", clean_name)
        df = pd.read_csv(self.root / "clean" / f"{clean_name}.csv",
                         index_col=0, parse_dates=True)
        derived = build(df)
        name = f"{clean_name}_{transform}"
        path = self.root / "derived" / f"{name}.csv"
        derived.to_csv(path)
        content, manifest = self._bind_digests(path)
        reg = {
            "layer": "derived",
            "file": str(path),
            "identity": {
                "instrument": clean_meta["identity"]["instrument"],
                "timeframe": clean_meta["identity"]["timeframe"],
                "timezone_name": clean_meta["identity"]["timezone_name"],
                "source": clean_meta["identity"]["source"],
                "source_timestamp": clean_meta["identity"]["source_timestamp"],
                "download_timestamp": clean_meta["identity"]["download_timestamp"],
                "sha256": content,
                "bars": len(derived),
                "schema_version": DATA_SCHEMA_VERSION,
                "quality": audit_ohlcv(derived)["quality"],
                "notes": [],
            },
            "manifest_digest": manifest,
            "audit": audit_ohlcv(derived),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "parent": {"layer": "clean", "name": clean_name,
                       "file_sha256": clean_meta["file_sha256"]},
            "transform": transform,
            "transform_version": "1",
        }
        self._write_meta("derived", name, reg)
        return reg

    # -- backtest reference -------------------------------------------------

    def ref(self, layer: str, name: str, *,
            allow_corrupt: bool = False) -> dict:
        """The dataset reference a backtest MUST name.  CORRUPT datasets are
        refused unless explicitly overridden (never silently used)."""
        meta = self._read_meta(layer, name)
        if meta["identity"]["quality"] == "CORRUPT" and not allow_corrupt:
            raise ValueError(
                f"{layer}/{name}: quality CORRUPT — refusing to issue a "
                f"backtest reference (explicit allow_corrupt required)")
        return {
            "layer": layer, "name": name, "file": meta["file"],
            "content_sha256": meta["identity"]["sha256"],
            "file_sha256": meta["file_sha256"],
            "manifest_digest": meta["manifest_digest"],
            "quality": meta["identity"]["quality"],
            "bars": meta["identity"]["bars"],
            "parent": meta.get("parent"),
        }

    def load(self, layer: str, name: str) -> pd.DataFrame:
        """Consumer entry point: the frame exactly as digested by
        :meth:`ref` — every backtest must load its data through here (or
        digest an identical frame) so the manifest names the stored bytes."""
        return self._read_back(self.root / layer / f"{name}.csv")

    # -- plumbing -----------------------------------------------------------

    @staticmethod
    def _read_back(path: Path) -> pd.DataFrame:
        """The frame exactly as any consumer of the store sees it."""
        return pd.read_csv(path, index_col=0, parse_dates=True)

    @classmethod
    def _bind_digests(cls, path: Path) -> tuple[str, str]:
        """(content_sha256, manifest_digest) of the frame as READ BACK from
        `path` — never from the in-memory writer's copy (the CSV round-trip
        changes dtypes; the binding must match what a backtest loads)."""
        df = cls._read_back(path)
        from .optimizer import _dataset_digest
        return content_digest(df), _dataset_digest(df)

    @staticmethod
    def _cleanable(audit: dict) -> bool:
        hard = {"duplicate_timestamp", "timestamp_disorder", "nonpositive_price",
                "nonfinite_price", "missing_columns", "empty"}
        return not any(f["type"] in hard for f in audit["findings"])

    def _meta_path(self, layer: str, name: str) -> Path:
        if layer not in self.LAYERS:
            raise ValueError(f"unknown layer {layer!r}")
        return self.root / layer / f"{name}.meta.json"

    def _write_meta(self, layer: str, name: str, reg: dict) -> None:
        self._meta_path(layer, name).write_text(
            json.dumps(reg, indent=2, sort_keys=True, default=str),
            encoding="utf-8")

    def _read_meta(self, layer: str, name: str) -> dict:
        p = self._meta_path(layer, name)
        if not p.exists():
            raise FileNotFoundError(f"no {layer} dataset named {name!r} "
                                    f"(register it first)")
        return json.loads(p.read_text(encoding="utf-8"))
