"""CLI entry point for the daily EURUSD Elliott walk-forward backtest."""
from pathlib import Path
from Modules.Elliott_Waves.Training.walk_forward import main

if __name__ == "__main__":
    main()
