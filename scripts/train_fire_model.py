
import os
import sys
import shutil
import argparse
import logging
import yaml
from pathlib import Path
from ultralytics import YOLO

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TrainFireModel")

PROJECT_ROOT = Path(__file__).resolve().parent
MODELS_DIR = PROJECT_ROOT / "backend" / "models"


def prepare_dataset_yaml(dataset_dir: Path, class_names: list) -> Path:
    """Creates or updates data.yaml configured for the dataset."""
    dataset_dir = dataset_dir.resolve()
    yaml_path = dataset_dir / "fire_data.yaml"

    # Check for train / val / valid / test directories
    train_images = dataset_dir / "train" / "images"
    val_images = dataset_dir / "val" / "images"
    valid_images = dataset_dir / "valid" / "images"
    test_images = dataset_dir / "test" / "images"

    train_path = "train/images" if train_images.exists() else "images"
    val_path = "val/images" if val_images.exists() else ("valid/images" if valid_images.exists() else "images")
    test_path = "test/images" if test_images.exists() else None

    # Check existing data.yaml for class names if default was provided
    existing_yaml = dataset_dir / "data.yaml"
    if existing_yaml.exists():
        try:
            with open(existing_yaml, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "names" in data and isinstance(data["names"], list):
                    if class_names == ["Fire"] or class_names == ["small_fire"]:
                        class_names = data["names"]
                        logger.info(f"Loaded class names from existing data.yaml: {class_names}")
        except Exception as e:
            logger.debug(f"Could not read existing data.yaml: {e}")

    yaml_dict = {
        "path": str(dataset_dir).replace("\\", "/"),
        "train": train_path,
        "val": val_path,
        "nc": len(class_names),
        "names": class_names
    }
    if test_path:
        yaml_dict["test"] = test_path

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(yaml_dict, f, default_flow_style=None, sort_keys=False)

    logger.info(f"Generated YAML config: {yaml_path}")
    return yaml_path


def train(
    dataset_dir: str,
    epochs: int = 50,
    batch_size: int = 16,
    img_size: int = 640,
    classes: str = "Fire",
    base_model: str = "yolov8n.pt",
    device: str = "auto",
    workers: int = 2
):
    dataset_path = Path(dataset_dir)
    if not dataset_path.exists():
        logger.error(f"Dataset directory not found: {dataset_path}")
        logger.info("Please create the directory and place your fire and small fire images inside.")
        return

    train_images = dataset_path / "train" / "images"
    if train_images.exists():
        img_count = len(list(train_images.glob("*.*")))
        logger.info(f"Found {img_count} training images in {train_images}")
        if img_count == 0:
            logger.error("No images found in training directory!")
            return

    class_list = [c.strip() for c in classes.split(",")]
    logger.info(f"Training for classes: {class_list}")

    yaml_path = prepare_dataset_yaml(dataset_path, class_list)

    logger.info(f"Loading base lightweight model: {base_model}")
    model = YOLO(base_model)

    import torch
    if device == "auto":
        resolved_device = 0 if torch.cuda.is_available() else "cpu"
    else:
        resolved_device = device

    logger.info(f"Training on device: {resolved_device} ({'GPU' if str(resolved_device) == '0' else 'CPU'})")

    logger.info(f"Starting training for {epochs} epochs at {img_size}x{img_size} (batch={batch_size}, workers={workers})...")
    results = model.train(
        data=str(yaml_path),
        epochs=epochs,
        batch=batch_size,
        imgsz=img_size,
        device=resolved_device,
        workers=workers,
        patience=15,
        save=True,
        plots=True,
        verbose=True,
        fliplr=0.5,
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
    )

    # Locate best trained model
    save_dir = Path(model.trainer.save_dir)
    best_pt = save_dir / "weights" / "best.pt"

    if best_pt.exists():
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        dest_pt = MODELS_DIR / "fire_yolov8.pt"
        shutil.copy(best_pt, dest_pt)
        logger.info(f"🎉 Model trained successfully and deployed to: {dest_pt}")

        # Try exporting to NCNN for Raspberry Pi
        try:
            logger.info("Exporting model to NCNN format for Raspberry Pi...")
            model_best = YOLO(str(dest_pt))
            model_best.export(format="ncnn")
            logger.info("Exported NCNN format for Raspberry Pi!")
        except Exception as e:
            logger.warning(f"Could not export NCNN: {e}")
    else:
        logger.warning(f"Training finished but best.pt not found in {save_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train PYRO-GUARD YOLOv8 on custom fire dataset")
    parser.add_argument("--data", type=str, default="dataset", help="Path to dataset directory (default: dataset)")
    parser.add_argument("--epochs", type=int, default=50, help="Number of training epochs (default: 50)")
    parser.add_argument("--batch", type=int, default=16, help="Batch size (default: 16)")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size (default: 640)")
    parser.add_argument("--classes", type=str, default="Fire", help="Comma-separated class names (default: Fire)")
    parser.add_argument("--base", type=str, default="yolov8n.pt", help="Base model weights (default: yolov8n.pt)")
    parser.add_argument("--device", type=str, default="auto", help="Device to use: auto, cpu, or 0 (default: auto)")
    parser.add_argument("--workers", type=int, default=2, help="Dataloader workers (default: 2)")

    args = parser.parse_args()
    train(
        dataset_dir=args.data,
        epochs=args.epochs,
        batch_size=args.batch,
        img_size=args.imgsz,
        classes=args.classes,
        base_model=args.base,
        device=args.device,
        workers=args.workers
    )
