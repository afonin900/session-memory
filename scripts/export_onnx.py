#!/usr/bin/env python3
"""One-time script: exports PyTorch model to ONNX format.

After running, the ONNX model is saved to models/multilingual-e5-base-onnx/.
The main code (core/embedder.py) will use this ONNX model instead of PyTorch.

Requirements: pip install optimum[exporters] sentence-transformers
Run once: python3 scripts/export_onnx.py
"""
import subprocess
import sys
from pathlib import Path

MODEL_NAME = "intfloat/multilingual-e5-base"
OUTPUT_DIR = Path(__file__).parent.parent / "models" / "multilingual-e5-base-onnx"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Exporting {MODEL_NAME} to ONNX...")
    subprocess.run([
        sys.executable, "-m", "optimum.exporters.onnx",
        "--model", MODEL_NAME,
        "--task", "feature-extraction",
        str(OUTPUT_DIR),
    ], check=True)

    print(f"Model exported to {OUTPUT_DIR}")

    # Quantize to INT8 for smaller size and faster inference
    print("Quantizing to INT8...")
    from onnxruntime.quantization import quantize_dynamic, QuantType

    onnx_path = OUTPUT_DIR / "model.onnx"
    quantized_path = OUTPUT_DIR / "model_quantized.onnx"

    quantize_dynamic(
        str(onnx_path),
        str(quantized_path),
        weight_type=QuantType.QInt8,
    )

    size_original = onnx_path.stat().st_size / 1024 / 1024
    size_quantized = quantized_path.stat().st_size / 1024 / 1024
    print(f"Original: {size_original:.0f}MB, Quantized: {size_quantized:.0f}MB")
    print("Done. Use model_quantized.onnx for inference.")


if __name__ == "__main__":
    main()
