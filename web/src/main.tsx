import React, { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Role = "coordinator" | "reviewer" | "student";

type Reviewer = {
  id: number;
  name: string;
  specialization: string;
  capacity: number;
  active_reviews: number;
};

type Criterion = {
  id: number;
  code: string;
  section: string;
  title: string;
  max_points: number;
  status: string;
  suggested_points: number | null;
  final_points: number | null;
  confidence: number | null;
  evidence: string[];
  feedback: string;
  final_feedback: string;
  human_decision: string | null;
};

type Submission = {
  id: number;
  title: string;
  repository_url: string;
  subdirectory: string;
  commit_sha: string | null;
  status: string;
  error_message: string | null;
  reviewer: { id: number; name: string } | null;
  suggested_points: number | null;
  assessed_points: number | null;
  confirmed_points: number;
  max_points: number;
  unresolved_criteria: number;
  created_at: string;
  due_at: string;
  approved_at: string | null;
  criteria: Criterion[];
  ai_usage_signal: {
    status: string;
    confidence: number | null;
    reasons: Array<{ description: string; evidence_refs: string[] }>;
    limitations: string;
  };
  events: Array<{ id: number; kind: string; message: string; created_at: string }>;
};

type Dashboard = {
  stats: { total: number; ready: number; approved: number; overdue: number };
  reviewers: Reviewer[];
  submissions: Submission[];
};

const roleLabels: Record<Role, string> = {
  coordinator: "Координатор",
  reviewer: "Ревьюер",
  student: "Студент"
};

const statusLabels: Record<string, string> = {
  received: "Получена",
  assigned: "Назначена",
  processing: "Проверяется",
  review_ready: "Ждёт ревьюера",
  human_review: "На проверке",
  approved: "Готово",
  error: "Ошибка"
};

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
    ...options
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Ошибка HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`status status-${status}`}>{statusLabels[status] ?? status}</span>;
}

function App() {
  const [role, setRole] = useState<Role>("coordinator");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [selected, setSelected] = useState<Submission | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    const data = await request<Dashboard>("/api/dashboard");
    setDashboard(data);
    setLoading(false);
    return data;
  }, []);

  const openSubmission = useCallback(async (id: number) => {
    const data = await request<Submission>(`/api/submissions/${id}`);
    setSelected(data);
    return data;
  }, []);

  useEffect(() => {
    loadDashboard().catch((error: Error) => {
      setMessage(error.message);
      setLoading(false);
    });
  }, [loadDashboard]);

  useEffect(() => {
    const hasProcessing = dashboard?.submissions.some((item) =>
      ["received", "assigned", "processing"].includes(item.status)
    );
    if (!hasProcessing) return;
    const timer = window.setInterval(() => {
      loadDashboard().then((data) => {
        if (selected) {
          const current = data.submissions.find((item) => item.id === selected.id);
          if (current && current.status !== selected.status) openSubmission(selected.id);
        }
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [dashboard, loadDashboard, openSubmission, selected]);

  const readySubmission = useMemo(
    () => dashboard?.submissions.find((item) => ["review_ready", "human_review"].includes(item.status)),
    [dashboard]
  );

  useEffect(() => {
    if (role === "reviewer" && !selected && readySubmission) {
      openSubmission(readySubmission.id).catch((error: Error) => setMessage(error.message));
    }
  }, [openSubmission, readySubmission, role, selected]);

  const refresh = async () => {
    await loadDashboard();
    if (selected) await openSubmission(selected.id);
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <i /><i /><i /><i />
          </span>
          <span>Avito AI Reviewer</span>
        </div>
        <nav className="role-switcher" aria-label="Режим интерфейса">
          {(Object.keys(roleLabels) as Role[]).map((item) => (
            <button
              type="button"
              key={item}
              className={role === item ? "active" : ""}
              onClick={() => setRole(item)}
            >
              {roleLabels[item]}
            </button>
          ))}
        </nav>
      </header>

      {message && (
        <div className="toast" role="alert">
          <span>{message}</span>
          <button type="button" onClick={() => setMessage(null)}>Закрыть</button>
        </div>
      )}

      {loading ? (
        <main className="loading">Загружаем рабочее пространство…</main>
      ) : role === "coordinator" ? (
        <CoordinatorView
          dashboard={dashboard!}
          onCreated={async (item) => {
            setSelected(item);
            await loadDashboard();
          }}
          onOpen={async (id) => {
            await openSubmission(id);
            setRole("reviewer");
          }}
          onError={setMessage}
        />
      ) : role === "reviewer" ? (
        <ReviewerView
          submissions={dashboard!.submissions}
          selected={selected}
          onOpen={openSubmission}
          onRefresh={refresh}
          onError={setMessage}
        />
      ) : (
        <StudentView
          submissions={dashboard!.submissions}
          selected={selected}
          onOpen={openSubmission}
          onError={setMessage}
        />
      )}
    </div>
  );
}

function CoordinatorView({
  dashboard,
  onCreated,
  onOpen,
  onError
}: {
  dashboard: Dashboard;
  onCreated: (item: Submission) => Promise<void>;
  onOpen: (id: number) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [subdirectory, setSubdirectory] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      const item = await request<Submission>("/api/submissions", {
        method: "POST",
        body: JSON.stringify({ repository_url: repositoryUrl, subdirectory })
      });
      setRepositoryUrl("");
      setSubdirectory("");
      await onCreated(item);
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="workspace">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Рабочее пространство координатора</p>
          <h1>Проверки без ручной очереди</h1>
          <p>Добавьте GitHub-работу — система назначит свободного ревьюера и подготовит проверку.</p>
        </div>
      </section>

      <section className="stats-grid">
        <Stat label="Всего работ" value={dashboard.stats.total} tone="blue" />
        <Stat label="Ждут ревьюера" value={dashboard.stats.ready} tone="purple" />
        <Stat label="Подтверждены" value={dashboard.stats.approved} tone="green" />
        <Stat label="Просрочены" value={dashboard.stats.overdue} tone="red" />
      </section>

      <div className="two-column">
        <section className="surface submission-form">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Новая работа</p>
              <h2>Получить из GitHub</h2>
            </div>
          </div>
          <form onSubmit={submit}>
            <label>
              Ссылка на репозиторий или Pull Request
              <input
                required
                type="url"
                value={repositoryUrl}
                placeholder="https://github.com/owner/repository"
                onChange={(event) => setRepositoryUrl(event.target.value)}
              />
            </label>
            <label>
              Папка с решением <span>необязательно</span>
              <input
                value={subdirectory}
                placeholder="Например: GO/Хорошее решение"
                onChange={(event) => setSubdirectory(event.target.value)}
              />
            </label>
            <button className="primary" type="submit" disabled={submitting}>
              {submitting ? "Добавляем…" : "Добавить работу"}
            </button>
          </form>
        </section>

        <section className="surface">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Команда проверки</p>
              <h2>Текущая загрузка</h2>
            </div>
          </div>
          <div className="reviewer-list">
            {dashboard.reviewers.map((reviewer) => (
              <div className="reviewer-row" key={reviewer.id}>
                <div className="avatar">{reviewer.name.slice(-1)}</div>
                <div className="reviewer-meta">
                  <strong>{reviewer.name}</strong>
                  <span>{reviewer.specialization}</span>
                </div>
                <div className="load-bar" aria-label={`${reviewer.active_reviews} из ${reviewer.capacity}`}>
                  <i style={{ width: `${Math.min(100, reviewer.active_reviews / reviewer.capacity * 100)}%` }} />
                </div>
                <span className="load-value">{reviewer.active_reviews}/{reviewer.capacity}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="surface submissions-surface">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Очередь</p>
            <h2>Домашние работы</h2>
          </div>
        </div>
        {dashboard.submissions.length === 0 ? (
          <div className="empty-state">
            <strong>Работ пока нет</strong>
            <span>Добавьте первую ссылку на GitHub.</span>
          </div>
        ) : (
          <div className="submission-table">
            {dashboard.submissions.map((item) => (
              <button className="submission-row" type="button" key={item.id} onClick={() => onOpen(item.id)}>
                <span className="submission-title">
                  <strong>{item.title}</strong>
                  <small>#{item.id} · до {formatDate(item.due_at)}</small>
                </span>
                <span>{item.reviewer?.name ?? "Не назначен"}</span>
                <StatusBadge status={item.status} />
                <span className="score">
                  {item.suggested_points === null ? "—" : `${item.suggested_points}/${item.assessed_points}`}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <article className={`stat-card stat-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function ReviewerView({
  submissions,
  selected,
  onOpen,
  onRefresh,
  onError
}: {
  submissions: Submission[];
  selected: Submission | null;
  onOpen: (id: number) => Promise<Submission>;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const queue = submissions.filter((item) => item.status !== "approved");
  return (
    <main className="review-layout">
      <aside className="queue-panel">
        <p className="eyebrow">Очередь ревьюера</p>
        <h2>Работы</h2>
        <div className="queue-list">
          {queue.length === 0 && <p className="muted">Нет работ на проверке.</p>}
          {queue.map((item) => (
            <button
              type="button"
              className={selected?.id === item.id ? "queue-item active" : "queue-item"}
              key={item.id}
              onClick={() => onOpen(item.id).catch((error: Error) => onError(error.message))}
            >
              <strong>{item.title}</strong>
              <span>{item.reviewer?.name}</span>
              <StatusBadge status={item.status} />
            </button>
          ))}
        </div>
      </aside>
      <section className="review-content">
        {!selected ? (
          <div className="empty-state tall">
            <strong>Выберите работу</strong>
            <span>Здесь появятся критерии, факты и предложения системы.</span>
          </div>
        ) : selected.status === "processing" || selected.status === "assigned" ? (
          <div className="processing-state">
            <div className="spinner" />
            <h1>Собираем материалы проверки</h1>
            <p>Фиксируем версию работы, читаем структуру и проверяем критерии.</p>
          </div>
        ) : selected.status === "error" ? (
          <div className="error-state">
            <h1>Проверка не завершилась</h1>
            <p>{selected.error_message}</p>
          </div>
        ) : (
          <ReviewDetail item={selected} onRefresh={onRefresh} onError={onError} />
        )}
      </section>
    </main>
  );
}

function ReviewDetail({
  item,
  onRefresh,
  onError
}: {
  item: Submission;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [savingId, setSavingId] = useState<number | null>(null);
  const sections = Array.from(new Set(item.criteria.map((criterion) => criterion.section)));
  const signalLabel = {
    low: "Низкий сигнал",
    medium: "Средний сигнал",
    high: "Высокий сигнал",
    insufficient_data: "Недостаточно данных",
    needs_review: "Нужно проверить"
  }[item.ai_usage_signal.status] ?? "Нужно проверить";

  const saveCriterion = async (criterion: Criterion, form: HTMLFormElement) => {
    const data = new FormData(form);
    setSavingId(criterion.id);
    try {
      await request(`/api/submissions/${item.id}/criteria/${criterion.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          final_points: Number(data.get("points")),
          final_feedback: String(data.get("feedback") ?? "")
        })
      });
      await onRefresh();
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setSavingId(null);
    }
  };

  const approve = async () => {
    try {
      await request(`/api/submissions/${item.id}/approve`, { method: "POST" });
      await onRefresh();
    } catch (error) {
      onError((error as Error).message);
    }
  };

  return (
    <div className="review-page">
      <div className="review-heading">
        <div>
          <p className="eyebrow">Работа #{item.id}</p>
          <h1>{item.title}</h1>
          <a href={item.repository_url} target="_blank" rel="noreferrer">Открыть в GitHub ↗</a>
        </div>
        <div className="review-total">
          <span>Предложено</span>
          <strong>{item.suggested_points ?? 0}/{item.assessed_points ?? 0}</strong>
          <small>{item.unresolved_criteria} требуют решения</small>
        </div>
      </div>

      <div className="responsibility-note">
        Итоговые баллы и комментарии подтверждает ревьюер. Предложения системы можно изменить.
      </div>

      {sections.map((section) => (
        <section className="criteria-section" key={section}>
          <h2>{section}</h2>
          {item.criteria.filter((criterion) => criterion.section === section).map((criterion) => (
            <form
              className={`criterion-card criterion-${criterion.status}`}
              key={criterion.id}
              onSubmit={(event) => {
                event.preventDefault();
                saveCriterion(criterion, event.currentTarget);
              }}
            >
              <div className="criterion-main">
                <div className="criterion-title-row">
                  <strong>{criterion.title}</strong>
                  <span>{criterion.max_points} баллов</span>
                </div>
                <p>{criterion.final_feedback || criterion.feedback}</p>
                {criterion.evidence.length > 0 && (
                  <details>
                    <summary>Показать подтверждения</summary>
                    <ul>{criterion.evidence.map((evidence) => <li key={evidence}>{evidence}</li>)}</ul>
                  </details>
                )}
              </div>
              <div className="criterion-controls">
                <label>
                  Балл
                  <input
                    name="points"
                    type="number"
                    min="0"
                    max={criterion.max_points}
                    defaultValue={criterion.final_points ?? ""}
                    required
                  />
                </label>
                <label className="feedback-field">
                  Комментарий
                  <textarea name="feedback" defaultValue={criterion.final_feedback || criterion.feedback} />
                </label>
                <div className="criterion-meta">
                  <span className={`decision decision-${criterion.status}`}>
                    {criterion.status === "needs_human" ? "Нужно проверить" : criterion.status === "pass" ? "Найдено" : "Не найдено"}
                  </span>
                  <span>{criterion.confidence === null ? "Без оценки уверенности" : `Уверенность ${Math.round(criterion.confidence * 100)}%`}</span>
                </div>
                <button className="secondary" type="submit" disabled={savingId === criterion.id}>
                  {savingId === criterion.id ? "Сохраняем…" : "Сохранить решение"}
                </button>
              </div>
            </form>
          ))}
        </section>
      ))}

      <section className="ai-signal">
        <div>
          <p className="eyebrow">Признаки использования ИИ</p>
          <h2>{item.ai_usage_signal.reasons.length ? "Есть основания для дополнительной проверки" : "Надёжный вывод сделать нельзя"}</h2>
          <p>{item.ai_usage_signal.limitations}</p>
          {item.ai_usage_signal.reasons.length > 0 && (
            <ul>
              {item.ai_usage_signal.reasons.map((reason) => (
                <li key={`${reason.description}-${reason.evidence_refs.join("-")}`}>
                  {reason.description}
                </li>
              ))}
            </ul>
          )}
        </div>
        <span className="status status-human">{signalLabel}</span>
      </section>

      <div className="review-actions">
        <a className="secondary button-link" href={`/api/submissions/${item.id}/export.xlsx`}>Скачать Excel</a>
        <button className="primary" type="button" onClick={approve} disabled={item.unresolved_criteria > 0 || item.status === "approved"}>
          {item.status === "approved" ? "Результат подтверждён" : "Подтвердить результат"}
        </button>
      </div>
    </div>
  );
}

function StudentView({
  submissions,
  selected,
  onOpen,
  onError
}: {
  submissions: Submission[];
  selected: Submission | null;
  onOpen: (id: number) => Promise<Submission>;
  onError: (message: string) => void;
}) {
  const approved = submissions.filter((item) => item.status === "approved");
  const item = selected?.status === "approved" ? selected : null;
  return (
    <main className="student-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Результаты студента</p>
          <h1>Что исправить и почему</h1>
          <p>Здесь показывается только результат, подтверждённый ревьюером.</p>
        </div>
      </section>
      <div className="student-grid">
        <aside className="surface student-list">
          <h2>Проверенные работы</h2>
          {approved.length === 0 && <p className="muted">Подтверждённых результатов пока нет.</p>}
          {approved.map((submission) => (
            <button type="button" key={submission.id} onClick={() => onOpen(submission.id).catch((error: Error) => onError(error.message))}>
              <strong>{submission.title}</strong>
              <span>{submission.confirmed_points}/{submission.max_points}</span>
            </button>
          ))}
        </aside>
        <section className="surface student-result">
          {!item ? (
            <div className="empty-state tall">
              <strong>Выберите проверенную работу</strong>
              <span>Результат появится после подтверждения ревьюером.</span>
            </div>
          ) : (
            <>
              <p className="eyebrow">Итог</p>
              <h2>{item.title}</h2>
              <div className="student-score">{item.confirmed_points}/{item.max_points}</div>
              {item.criteria.filter((criterion) => (criterion.final_points ?? 0) < criterion.max_points).map((criterion) => (
                <article key={criterion.id}>
                  <strong>{criterion.title}</strong>
                  <span>{criterion.final_points}/{criterion.max_points}</span>
                  <p>{criterion.final_feedback || criterion.feedback}</p>
                </article>
              ))}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
