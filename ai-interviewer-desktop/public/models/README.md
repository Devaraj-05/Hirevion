# Bundled models

The desktop app ships its models and never downloads code or models at run time.

| File | Source | Licence | SHA-256 |
|---|---|---|---|
| `blaze_face_short_range.tflite` | MediaPipe BlazeFace short-range face detector, float16, version 1: `https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite` | Apache-2.0 | `b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f` |
| `efficientdet_lite2.tflite` | MediaPipe EfficientDet-Lite2 object detector (COCO labels), int8, version 1, for the third eye's placement check (C8-3; Lite0 gave a laptop seen from the side 0.13, Lite2 0.6-0.7): `https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite2/int8/1/efficientdet_lite2.tflite` | Apache-2.0 | `b3f50554cb0ea559e90328845f7d9ba4d13c8bff372914d24e06bc8bb72fa896` |

To update a model, download the new version, update its row (source URL, version and
SHA-256), and re-run the media spike (`HV_SPIKE=media:60`) to compare frame rate and
inference time.
