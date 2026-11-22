"""Loopback OCR service and annotated dataset API, authenticated by API key."""
from __future__ import annotations
import hmac
from pathlib import Path
from typing import Literal
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from . import __version__
from .dataset import DatasetStore, DatasetError, MissingSample, VersionConflict
from .engine import EngineUnavailable, OCRService
from .image_io import InvalidImage, decode_base64
from .paddle_export import export_detection_zip
from .rec_export import export_recognition_zip
from .training import TrainingError, TrainingManager, build_plan
from .evaluation import evaluate_recognition
from .live_evaluation import evaluate_reviewed_test
from .models import ModelRegistry
from .settings import api_key as configured_key


class OCRRequest(BaseModel):
    image_base64: str = Field(..., description="Base64 of a local image (no remote URLs)")
    engine: Literal["auto", "rapidocr", "tesseract"] = "auto"


class SampleRequest(BaseModel):
    image_base64: str
    source: str = Field(default="local", max_length=160)


class AnnotationLine(BaseModel):
    text: str
    box: list[list[float]]


class AnnotationsRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    lines: list[AnnotationLine] = Field(max_length=512)


class SamplePatch(BaseModel):
    expected_revision: int = Field(ge=1)
    status: Literal["draft", "reviewed"] | None = None
    split: Literal["unassigned", "train", "val", "test"] | None = None
    source: str | None = Field(default=None, max_length=160)


class TrainingRequest(BaseModel):
    paddle_repo: str = Field(min_length=1, max_length=1024)
    dataset_dir: str = Field(min_length=1, max_length=1024)
    pretrained_model: str = Field(min_length=1, max_length=1024)
    training_python: str | None = Field(default=None, min_length=1, max_length=1024)
    epochs: int = Field(default=10, ge=1, le=50)
    batch_size: int = Field(default=4, ge=1, le=32)
    use_gpu: bool = False
    resume_run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    resume_checkpoint: Literal["latest", "best_accuracy"] = "latest"


class RecognitionEvaluationRequest(BaseModel):
    dataset_dir: str = Field(min_length=1, max_length=1024)
    predictions_path: str = Field(min_length=1, max_length=1024)


class ReviewedTestEvaluationRequest(BaseModel):
    engine: Literal["auto", "rapidocr", "tesseract"] = "auto"
    limit: int = Field(default=5, ge=1, le=20)
    offset: int = Field(default=0, ge=0)


class CheckpointRegistrationRequest(BaseModel):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    filename: str = Field(min_length=1, max_length=128)


def create_app(service: OCRService | None = None, token: str | None = None,
               store: DatasetStore | None = None) -> FastAPI:
    engine = service or OCRService()
    secret = token if token is not None else configured_key()
    app = FastAPI(title="LocalOCR", version=__version__,
                  description="Offline local image OCR and manually reviewed training data preparation")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    # Store initialization is lazy: CLI-only users shouldn't create a database.
    dataset = store
    training_manager: TrainingManager | None = None
    model_registry: ModelRegistry | None = None

    def get_model_registry() -> ModelRegistry:
        nonlocal model_registry
        if model_registry is None:
            model_registry = ModelRegistry()
        return model_registry


    def get_training_manager() -> TrainingManager:
        nonlocal training_manager
        if training_manager is None:
            training_manager = TrainingManager()
        return training_manager


    def get_dataset() -> DatasetStore:
        nonlocal dataset
        if dataset is None:
            dataset = DatasetStore()
        return dataset

    def authorize(x_api_key: str | None = Header(default=None)) -> None:
        if not x_api_key or not hmac.compare_digest(x_api_key, secret):
            raise HTTPException(status_code=401, detail="Invalid X-API-Key")

    def fail_dataset(err: Exception) -> None:
        if isinstance(err, MissingSample):
            raise HTTPException(status_code=404, detail=str(err)) from err
        if isinstance(err, VersionConflict):
            raise HTTPException(status_code=409, detail=str(err)) from err
        raise HTTPException(status_code=400, detail=str(err)) from err

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "img-src 'self' blob: data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/v1/engines", dependencies=[Depends(authorize)])
    def engines():
        return {"available": engine.backends(), "auto_priority": ["rapidocr", "tesseract"]}

    @app.post("/v1/ocr", dependencies=[Depends(authorize)])
    def recognize(req: OCRRequest):
        try:
            image = decode_base64(req.image_base64)
            return engine.run(image, engine=req.engine).as_dict()
        except InvalidImage as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except EngineUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/studio", response_class=HTMLResponse)
    def studio():
        path = Path(__file__).parent / "web" / "index.html"
        return path.read_text(encoding="utf-8")

    @app.get("/assets/studio.css")
    def css():
        return FileResponse(Path(__file__).parent / "web" / "studio.css", media_type="text/css")

    @app.get("/assets/studio.js")
    def js():
        return FileResponse(Path(__file__).parent / "web" / "studio.js", media_type="text/javascript")

    @app.get("/v1/samples", dependencies=[Depends(authorize)])
    def samples(limit: int = 50, offset: int = 0):
        if limit < 1 or limit > 100 or offset < 0:
            raise HTTPException(status_code=400, detail="limit must be 1..100; offset >= 0")
        return get_dataset().list(limit, offset)

    @app.post("/v1/samples", dependencies=[Depends(authorize)], status_code=201)
    def add_sample(req: SampleRequest):
        try:
            return get_dataset().add(decode_base64(req.image_base64), req.source)
        except (DatasetError, InvalidImage) as e:
            fail_dataset(e)

    @app.get("/v1/samples/{sample_id}", dependencies=[Depends(authorize)])
    def read_sample(sample_id: str):
        try:
            return get_dataset().get(sample_id)
        except DatasetError as e:
            fail_dataset(e)

    @app.get("/v1/samples/{sample_id}/image", dependencies=[Depends(authorize)])
    def sample_image(sample_id: str):
        try:
            return Response(content=get_dataset().image(sample_id), media_type="image/png")
        except DatasetError as e:
            fail_dataset(e)

    @app.put("/v1/samples/{sample_id}/annotations", dependencies=[Depends(authorize)])
    def save_annotations(sample_id: str, req: AnnotationsRequest):
        try:
            return get_dataset().put_annotations(sample_id, req.expected_revision,
                                                 [l.model_dump() for l in req.lines])
        except DatasetError as e:
            fail_dataset(e)

    @app.patch("/v1/samples/{sample_id}", dependencies=[Depends(authorize)])
    def patch_sample(sample_id: str, req: SamplePatch):
        try:
            return get_dataset().patch(sample_id, req.expected_revision, req.status, req.split, req.source)
        except DatasetError as e:
            fail_dataset(e)

    @app.delete("/v1/samples/{sample_id}", dependencies=[Depends(authorize)], status_code=204)
    def delete_sample(sample_id: str, expected_revision: int):
        try:
            get_dataset().delete(sample_id, expected_revision)
            return Response(status_code=204)
        except DatasetError as e:
            fail_dataset(e)

    @app.post("/v1/samples/{sample_id}/suggest", dependencies=[Depends(authorize)])
    def suggest(sample_id: str, engine_name: Literal["auto", "rapidocr", "tesseract"] = "auto"):
        """Non-mutating OCR suggestion; not treated as manually reviewed ground truth."""
        try:
            from .image_io import load_image
            return engine.run(load_image(get_dataset().image(sample_id)), engine_name).as_dict()
        except DatasetError as e:
            fail_dataset(e)
        except EngineUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

    @app.get("/v1/datasets/stats", dependencies=[Depends(authorize)])
    def dataset_stats():
        return get_dataset().stats()

    @app.get("/v1/datasets/export", dependencies=[Depends(authorize)])
    def export_dataset(reviewed_only: bool = True):
        try:
            blob = get_dataset().export_zip(reviewed_only)
            return Response(content=blob, media_type="application/zip",
                            headers={"Content-Disposition": 'attachment; filename="localocr-dataset.zip"'})
        except DatasetError as e:
            fail_dataset(e)

    @app.get("/v1/datasets/export/paddle-det", dependencies=[Depends(authorize)])
    def export_paddle_det():
        """Export only human-reviewed PaddleOCR text-detection labels."""
        try:
            blob = export_detection_zip(get_dataset())
            return Response(
                content=blob, media_type="application/zip",
                headers={"Content-Disposition": 'attachment; filename="localocr-paddle-det.zip"'},
            )
        except DatasetError as e:
            fail_dataset(e)

    @app.get("/v1/datasets/export/paddle-rec", dependencies=[Depends(authorize)])
    def export_paddle_rec():
        """Human-reviewed, explicitly assigned quadrilateral text crops."""
        try:
            return Response(
                content=export_recognition_zip(get_dataset()),
                media_type="application/zip",
                headers={"Content-Disposition": 'attachment; filename="localocr-paddle-rec.zip"'},
            )
        except DatasetError as e:
            fail_dataset(e)

    def training_plan(req: TrainingRequest):
        try:
            return build_plan(
                req.paddle_repo, req.dataset_dir, req.pretrained_model,
                epochs=req.epochs, batch_size=req.batch_size, use_gpu=req.use_gpu,
                resume_run_id=req.resume_run_id,
                resume_checkpoint=req.resume_checkpoint,
                training_python=req.training_python,
            )
        except (TrainingError, OSError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/v1/training/plan", dependencies=[Depends(authorize)])
    def plan_training(req: TrainingRequest):
        return training_plan(req)

    @app.post("/v1/training/start", dependencies=[Depends(authorize)])
    def start_training(req: TrainingRequest):
        plan = training_plan(req)
        try:
            return get_training_manager().start(plan)
        except (TrainingError, OSError) as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    @app.get("/v1/training/status", dependencies=[Depends(authorize)])
    def training_status():
        return get_training_manager().status()

    @app.post("/v1/training/cancel", dependencies=[Depends(authorize)])
    def cancel_training():
        try:
            return get_training_manager().cancel()
        except (TrainingError, OSError) as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    @app.get("/v1/training/history", dependencies=[Depends(authorize)])
    def training_history(limit: int = 20):
        return {"items": get_training_manager().history(limit)}

    @app.post("/v1/evaluation/recognition", dependencies=[Depends(authorize)])
    def recognition_evaluation(req: RecognitionEvaluationRequest):
        try:
            return evaluate_recognition(req.dataset_dir, req.predictions_path)
        except (TrainingError, OSError, UnicodeError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/v1/evaluation/reviewed-test", dependencies=[Depends(authorize)])
    def evaluate_current_ocr(req: ReviewedTestEvaluationRequest):
        """Run local OCR on held-out reviewed image crops; never mutate labels."""
        try:
            return evaluate_reviewed_test(get_dataset(), engine, req.engine,
                                          req.limit, req.offset)
        except EngineUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except (DatasetError, InvalidImage, OSError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/v1/models", dependencies=[Depends(authorize)])
    def list_registered_models():
        try:
            return {"items": get_model_registry().list()}
        except (TrainingError, OSError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/v1/models/register", dependencies=[Depends(authorize)])
    def register_checkpoint(req: CheckpointRegistrationRequest):
        try:
            return get_model_registry().register(req.run_id, req.filename)
        except (TrainingError, OSError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    return app


app = create_app()
