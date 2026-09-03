from app.rubric import TOTAL_POINTS
from app.services.github import RepositorySnapshot
from app.services.review import evaluate


def snapshot() -> RepositorySnapshot:
    files = {
        "cmd/service/main.go": """
            package main
            import ("net/http"; "os"; "os/signal")
            func main() {
                _ = os.Getenv("PORT")
                r.Get("/ping", handlers.Ping)
                r.Head("/healthcheck", handlers.Healthcheck)
                server := &http.Server{}
                signal.Notify(make(chan os.Signal, 1))
                server.Shutdown(context.Background())
                log.Println("Shutting down service-courier")
                repository := NewRepository()
                _ = repository
            }
        """,
        "internal/handler/ping.go": """
            package handler
            func Ping() { json.NewEncoder(w).Encode(map[string]string{"message": "pong"}) }
            func Healthcheck() { w.WriteHeader(http.StatusNoContent) }
            type Usecase interface { Get(id int) error }
        """,
        "internal/usecase/courier.go": """
            package usecase
            type Repository interface { Get(id int) error }
            func NewUsecase(repo Repository) *Usecase { return &Usecase{} }
        """,
        "internal/repository/courier.go": """
            package repository
            import "github.com/jackc/pgx/v5"
            func NewRepository() *Repository { return &Repository{} }
            const get = "SELECT * FROM couriers WHERE id = $1"
        """,
        "internal/model/courier.go": "package model",
        "migrations/001_couriers.sql": """
            -- +goose Up
            CREATE TABLE couriers (id BIGSERIAL PRIMARY KEY, phone TEXT UNIQUE);
        """,
        "internal/handler/courier.go": """
            package handler
            // GET /courier/{id}
            // GET /couriers
            // POST /courier
            // PUT /courier
        """,
        "internal/handler/courier_test.go": "package handler",
    }
    return RepositorySnapshot(
        owner="example",
        repository="course-go",
        branch="main",
        commit_sha="abc123",
        files=files,
        all_paths=tuple(files),
    )


def test_rubric_totals_one_hundred_points() -> None:
    assert TOTAL_POINTS == 100


def test_review_finds_objective_evidence_and_defers_judgement() -> None:
    findings = evaluate(snapshot())
    by_code = {finding.criterion.code: finding for finding in findings}

    assert by_code["foundation.ping"].status == "pass"
    assert by_code["foundation.ping"].suggested_points == 4
    assert by_code["architecture.layers"].status == "pass"
    assert by_code["architecture.quality"].status == "needs_human"
    assert by_code["architecture.quality"].suggested_points is None


def test_ping_requires_route_and_expected_response() -> None:
    incomplete = RepositorySnapshot(
        owner="example",
        repository="course-go",
        branch="main",
        commit_sha="abc123",
        files={"main.go": 'router.Get("/ping", Ping)'},
        all_paths=("main.go",),
    )

    finding = next(item for item in evaluate(incomplete) if item.criterion.code == "foundation.ping")

    assert finding.status == "fail"
    assert finding.suggested_points == 0
