"""Tests for the MT5 install script (deploys into a fake data folder)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import install_mql5


def test_install_into_fake_data_folder(tmp_path):
    data_folder = tmp_path / "MQL5" / "Terminal" / "ABCD1234"
    (data_folder / "MQL5").mkdir(parents=True)

    n = install_mql5.install(data_folder)
    assert n == 4  # Include, Experts, Scripts, Presets

    ea = data_folder / "MQL5" / "Experts" / "Mql5Bot" / "Mql5Bot.mq5"
    assert ea.exists() and ea.read_text(encoding="utf-8").startswith("//")
    inc = data_folder / "MQL5" / "Include" / "Mql5Bot" / "Config.mqh"
    assert inc.exists()
    script = data_folder / "MQL5" / "Scripts" / "Mql5Bot" / "Mql5BotDownloadData.mq5"
    assert script.exists()
    presets = list((data_folder / "MQL5" / "Presets" / "Mql5Bot").glob("*.set"))
    assert len(presets) == 5


def test_install_is_idempotent_without_force(tmp_path):
    data_folder = tmp_path / "MQL5" / "Terminal" / "ABCD1234"
    (data_folder / "MQL5").mkdir(parents=True)
    assert install_mql5.install(data_folder) == 4
    # second run without --force: everything already installed -> skipped
    assert install_mql5.install(data_folder) == 0
    # with force: overwrites everything again
    assert install_mql5.install(data_folder, force=True) == 4


def test_main_rejects_missing_folder(tmp_path):
    assert install_mql5.main(["--folder", str(tmp_path / "nope")]) == 1
