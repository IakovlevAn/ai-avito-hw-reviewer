import React, { FormEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/manrope";
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
  source_url: string;
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
  code_comments: Array<{
    id: number;
    file_path: string;
    line_number: number;
    body: string;
    created_at: string;
  }>;
  execution_check: {
    status: string;
    go_version: string | null;
    dependencies_ok: boolean | null;
    tests_ok: boolean | null;
    vet_ok: boolean | null;
    has_tests: boolean;
    duration_seconds: number | null;
    output_summary: string;
  } | null;
};

type RepositoryFiles = {
  commit_sha: string;
  files: Array<{ path: string; content: string; url: string }>;
};

type RubricResponse = {
  total_points: number;
  criteria: Array<{ code: string; section: string; title: string; max_points: number }>;
};

const repositoryFilesCache = new Map<number, RepositoryFiles>();

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
  received: "Зарегистрирована",
  assigned: "Назначена",
  processing: "Предварительная проверка",
  review_ready: "Требуется решение",
  human_review: "Ручная проверка",
  approved: "Подтверждена",
  error: "Ошибка"
};

const activeHomework = {
  code: "GO-HW-01",
  course: "Backend-разработка на Go",
  title: "Сервис курьеров",
  submissionTitle: "Домашняя работа · Сервис курьеров",
  deadline: "10 сентября 2026, 23:59 МСК",
  summary: "Разработайте Go-сервис с HTTP API для управления курьерами, хранением данных в PostgreSQL и понятным разделением ответственности в коде.",
  stages: [
    {
      title: "Этап 1. Базовый HTTP-сервис",
      objective: "Подготовить каркас Go-приложения, настроить запуск HTTP-сервера и служебные endpoint’ы.",
      requirements: [
        "Организовать проект по логическим каталогам: cmd, internal и при необходимости pkg.",
        "Читать PORT из .env и разрешить переопределение через флаг --port.",
        "Реализовать GET /ping: статус 200 и JSON { \"message\": \"pong\" }.",
        "Реализовать HEAD /healthcheck: статус 204 без тела ответа.",
        "Обрабатывать SIGINT и SIGTERM, завершать сервер через context и выводить в stdout сообщение Shutting down service-courier."
      ]
    },
    {
      title: "Этап 2. PostgreSQL и API курьеров",
      objective: "Подключить PostgreSQL, создать схему данных и реализовать операции с курьерами.",
      requirements: [
        "Настраивать host, port, dbname, user и password через .env.",
        "Создать миграцию goose для таблицы couriers с полями id, name, phone, status, created_at и updated_at; phone должен быть уникальным.",
        "Реализовать GET /courier/{id}, GET /couriers, POST /courier и PUT /courier.",
        "Возвращать предусмотренные условием статусы 200, 201, 400, 404 и 409.",
        "Использовать SQL-плейсхолдеры $1, $2 и далее; корректно закрывать ресурсы и обрабатывать ошибки."
      ]
    },
    {
      title: "Этап 3. Архитектура",
      objective: "Разделить код по ответственности и явно оформить зависимости между слоями.",
      requirements: [
        "Выделить HTTP-слой, бизнес-логику, репозиторий и бизнес-сущности.",
        "Определить интерфейсы между handler и usecase, а также между usecase и repository.",
        "Передавать зависимости через конструкторы и собирать их в main.go.",
        "Сохранить работоспособность сервиса после рефакторинга.",
        "Не переусложнять решение; соблюдать Low Coupling / High Cohesion, SOLID и DRY."
      ]
    }
  ],
  sections: [
    { title: "Базовый сервис", points: 30 },
    { title: "Данные и API", points: 40 },
    { title: "Архитектура", points: 30 }
  ]
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

function InfoTip({ text }: { text: string }) {
  const id = React.useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState({ top: -1000, left: -1000, arrowLeft: 20, placement: "top" });

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    const tooltip = tooltipRef.current;
    if (!trigger || !tooltip) return;

    const triggerRect = trigger.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const margin = 12;
    const gap = 10;
    const centeredLeft = triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2;
    const left = Math.max(margin, Math.min(centeredLeft, window.innerWidth - tooltipRect.width - margin));
    const above = triggerRect.top - tooltipRect.height - gap;
    const placement = above >= margin ? "top" : "bottom";
    const top = placement === "top" ? above : triggerRect.bottom + gap;
    const arrowLeft = Math.max(
      14,
      Math.min(triggerRect.left + triggerRect.width / 2 - left, tooltipRect.width - 14)
    );
    setPosition({ top, left, arrowLeft, placement });
  }, []);

  useLayoutEffect(() => {
    if (visible) updatePosition();
  }, [text, updatePosition, visible]);

  useEffect(() => {
    if (!visible) return;
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [updatePosition, visible]);

  return (
    <span
      className="info-tip-anchor"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => {
        if (document.activeElement !== triggerRef.current) setVisible(false);
      }}
    >
      <button
        ref={triggerRef}
        className="info-tip"
        type="button"
        aria-label={text}
        aria-describedby={visible ? id : undefined}
        aria-expanded={visible}
        onFocus={() => setVisible(true)}
        onBlur={() => setVisible(false)}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setVisible(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") setVisible(false);
        }}
      >
        ?
      </button>
      {visible && createPortal(
        <div
          ref={tooltipRef}
          id={id}
          role="tooltip"
          className={`tooltip-popover tooltip-${position.placement}`}
          style={{
            top: position.top,
            left: position.left,
            "--tooltip-arrow-left": `${position.arrowLeft}px`
          } as React.CSSProperties}
        >
          {text}
        </div>,
        document.body
      )}
    </span>
  );
}

function studentNameFor(item: Submission): string {
  const prefix = `${activeHomework.submissionTitle} · `;
  return item.title.startsWith(prefix) ? item.title.slice(prefix.length) : item.title;
}

function defaultCodePath(files: RepositoryFiles["files"]): string | null {
  return files.find((file) => file.path === "cmd/main.go")?.path
    ?? files.find((file) => file.path.endsWith("/main.go"))?.path
    ?? files.find((file) => file.path.endsWith(".go"))?.path
    ?? files[0]?.path
    ?? null;
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
          <svg className="avito-symbol" width="33" height="30" viewBox="0 0 410 380" aria-hidden="true">
            <circle cx="122.965" cy="256.711" r="122.559" fill="#04E061" />
            <circle cx="335.574" cy="289.745" r="74.057" fill="#FF4053" />
            <circle cx="146.404" cy="72.347" r="45.828" fill="#965EEB" />
            <circle cx="306.803" cy="100.051" r="99.645" fill="#00AAFF" />
          </svg>
          <svg className="avito-wordmark" width="73" height="30" viewBox="0 0 73 30" aria-label="Avito">
            <path d="M9.664 1.08.927 23.891H5.62l1.796-4.767h9.27l1.804 4.767h4.658L14.465 1.079h-4.8Zm-.637 13.858 3.051-8.026 3.04 8.026H9.027Zm19.73 3.071-3.79-10.143h-4.476l6.103 16.026h4.438l5.995-16.026H32.55l-3.793 10.143Zm13.901-10.143h-4.26v16.026h4.26V7.866Zm-2.132-1.155a3.106 3.106 0 1 0 0-6.211 3.106 3.106 0 0 0 0 6.211ZM51.102 3.59h-4.25v4.25h-2.49v3.86h2.49v6.81c0 3.863 2.13 5.524 5.127 5.524a7.338 7.338 0 0 0 2.947-.576v-3.97a4.755 4.755 0 0 1-1.588.289c-1.302 0-2.24-.506-2.24-2.24V11.7h3.828V7.878h-3.824V3.59Zm12.781 3.986a8.305 8.305 0 1 0-.007 16.61 8.305 8.305 0 0 0 .007-16.61Zm0 12.36a4.044 4.044 0 1 1 4.04-4.044 4.036 4.036 0 0 1-4.04 4.029v.015Z" />
          </svg>
          <span className="brand-divider" aria-hidden="true" />
          <span className="brand-product">AI Reviewer</span>
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
        <main className="loading">Загрузка данных…</main>
      ) : role === "coordinator" ? (
        <CoordinatorView
          dashboard={dashboard!}
          onRefresh={async () => { await loadDashboard(); }}
          onError={setMessage}
          onOpen={async (id) => {
            await openSubmission(id);
            setRole("reviewer");
          }}
        />
      ) : role === "reviewer" ? (
        <ReviewerView
          reviewers={dashboard!.reviewers}
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
          onCreated={async (item) => {
            setSelected(item);
            await loadDashboard();
          }}
          onError={setMessage}
        />
      )}
    </div>
  );
}

function CoordinatorView({
  dashboard,
  onRefresh,
  onError,
  onOpen
}: {
  dashboard: Dashboard;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
  onOpen: (id: number) => Promise<void>;
}) {
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [reassigningId, setReassigningId] = useState<number | null>(null);
  const filteredSubmissions = dashboard.submissions.filter((item) => {
    const matchesQuery = studentNameFor(item).toLocaleLowerCase("ru-RU").includes(query.trim().toLocaleLowerCase("ru-RU"));
    const matchesStatus = statusFilter === "all"
      || (statusFilter === "attention" && (item.status === "error" || (item.status !== "approved" && new Date(item.due_at) < new Date())))
      || item.status === statusFilter;
    return matchesQuery && matchesStatus;
  });

  const reassign = async (submissionId: number, reviewerId: number) => {
    setReassigningId(submissionId);
    try {
      await request(`/api/submissions/${submissionId}/reviewer`, {
        method: "PATCH",
        body: JSON.stringify({ reviewer_id: reviewerId })
      });
      await onRefresh();
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setReassigningId(null);
    }
  };

  return (
    <main className="workspace">
      <section className="page-heading">
        <div>
          <h1>Проверка домашних работ</h1>
          <p>{activeHomework.course} · {activeHomework.code}</p>
        </div>
        <div className="page-context">
          <span>Текущая роль</span>
          <strong>Координатор</strong>
        </div>
      </section>

      <section className="surface assignment-summary">
        <div className="section-heading">
          <div>
            <span className="field-caption">Текущая домашняя работа</span>
            <h2>{activeHomework.title}</h2>
          </div>
          <span className="status status-active">Приём открыт</span>
        </div>
        <div className="assignment-fields">
          <div>
            <span>Идентификатор <InfoTip text="Код домашней работы в рамках курса." /></span>
            <strong>{activeHomework.code}</strong>
          </div>
          <div>
            <span>Срок сдачи <InfoTip text="После указанного времени новая отправка считается просроченной." /></span>
            <strong>{activeHomework.deadline}</strong>
          </div>
          <div>
            <span>Способ сдачи <InfoTip text="Студент передаёт ссылку на репозиторий или Pull Request." /></span>
            <strong>GitHub</strong>
          </div>
          <div>
            <span>Максимальный балл</span>
            <strong>100</strong>
          </div>
        </div>
      </section>

      <section className="stats-grid">
        <Stat label="Все отправки" value={dashboard.stats.total} help="Все зарегистрированные отправки по текущей домашней работе." />
        <Stat label="Ожидают решения" value={dashboard.stats.ready} help="Предварительная проверка завершена; требуется решение ревьюера." />
        <Stat label="Подтверждены" value={dashboard.stats.approved} help="Работы с подтверждёнными баллами и комментариями." />
        <Stat label="Срок ревью истёк" value={dashboard.stats.overdue} help="Работы без подтверждённого результата после установленного срока проверки." />
      </section>

      <section className="surface coordinator-reviewers">
        <div className="section-heading">
          <div>
            <h2>Распределение по ревьюерам</h2>
            <p>Учитываются все работы без подтверждённого результата.</p>
          </div>
        </div>
        <div className="reviewer-table-head">
          <span>Ревьюер</span>
          <span>Специализация</span>
          <span>Загрузка</span>
          <span>Активные <InfoTip text="Количество активных работ и лимит параллельных проверок." /></span>
        </div>
        <div className="reviewer-list">
          {dashboard.reviewers.map((reviewer) => (
            <div className="reviewer-row" key={reviewer.id}>
              <strong>{reviewer.name}</strong>
              <span>{reviewer.specialization}</span>
              <div className="load-bar" aria-label={`${reviewer.active_reviews} из ${reviewer.capacity}`}>
                <i style={{ width: `${Math.min(100, reviewer.active_reviews / reviewer.capacity * 100)}%` }} />
              </div>
              <span className="load-value">{reviewer.active_reviews}/{reviewer.capacity}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="surface submissions-surface">
        <div className="section-heading">
          <div>
            <h2>Очередь проверки</h2>
            <p>Контроль статусов, сроков и ручная корректировка назначения.</p>
          </div>
          <span className="queue-count">Показано: {filteredSubmissions.length}</span>
        </div>
        <div className="queue-filters">
          <label>
            Поиск по студенту
            <input value={query} placeholder="Имя студента" onChange={(event) => setQuery(event.target.value)} />
          </label>
          <label>
            Статус
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="all">Все статусы</option>
              <option value="review_ready">Требуется решение</option>
              <option value="human_review">Ручная проверка</option>
              <option value="approved">Подтверждена</option>
              <option value="attention">Требуют внимания</option>
            </select>
          </label>
        </div>
        {dashboard.submissions.length === 0 ? (
          <div className="empty-state">
            <strong>Зарегистрированные работы отсутствуют</strong>
            <span>Новые отправки будут добавлены в эту очередь.</span>
          </div>
        ) : (
          <div className="submission-table">
            <div className="submission-table-head">
              <span>Студент</span>
              <span>Ревьюер</span>
              <span>Статус</span>
              <span>Балл <InfoTip text="Предварительная сумма по критериям, которые система смогла оценить." /></span>
            </div>
            {filteredSubmissions.map((item) => (
              <div className="submission-row" key={item.id}>
                <button className="submission-open" type="button" onClick={() => onOpen(item.id)}>
                  <strong>{studentNameFor(item)}</strong>
                  <small>Отправка #{item.id} · срок ревью {formatDate(item.due_at)}</small>
                </button>
                <select
                  className="reviewer-inline"
                  aria-label={`Ревьюер для отправки ${item.id}`}
                  value={item.reviewer?.id ?? ""}
                  disabled={reassigningId === item.id}
                  onChange={(event) => reassign(item.id, Number(event.target.value))}
                >
                  {dashboard.reviewers.map((reviewer) => (
                    <option value={reviewer.id} key={reviewer.id}>{reviewer.name}</option>
                  ))}
                </select>
                <StatusBadge status={item.status} />
                <span className="score">
                  {item.suggested_points === null ? "—" : `${item.suggested_points}/${item.assessed_points}`}
                </span>
              </div>
            ))}
            {filteredSubmissions.length === 0 && (
              <div className="empty-state compact"><span>Работы по выбранным условиям отсутствуют.</span></div>
            )}
          </div>
        )}
      </section>
    </main>
  );
}

function GitHubSubmissionForm({
  studentName,
  onStudentNameChange,
  onCreated,
  onError
}: {
  studentName: string;
  onStudentNameChange: (value: string) => void;
  onCreated: (item: Submission) => Promise<void>;
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
        body: JSON.stringify({
          repository_url: repositoryUrl,
          subdirectory,
          title: `${activeHomework.submissionTitle} · ${studentName.trim()}`
        })
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
    <form className="student-submit-form" onSubmit={submit}>
      <label>
        <span className="field-label">Имя студента <InfoTip text="Имя используется для отображения работы в очереди ревьюера." /></span>
        <input
          required
          value={studentName}
          placeholder="Имя и фамилия"
          onChange={(event) => onStudentNameChange(event.target.value)}
        />
      </label>
      <label>
        <span className="field-label">GitHub-ссылка <InfoTip text="Укажите публичный репозиторий или Pull Request с решением текущей домашней работы." /></span>
        <input
          required
          type="url"
          value={repositoryUrl}
          placeholder="https://github.com/owner/repository"
          onChange={(event) => setRepositoryUrl(event.target.value)}
        />
      </label>
      <button className="primary" type="submit" disabled={submitting}>
        {submitting ? "Регистрация…" : "Передать на проверку"}
      </button>
      <details className="advanced-field">
        <summary>Дополнительные параметры</summary>
        <label>
          <span className="field-label">Путь к каталогу <InfoTip text="Заполните, если решение находится не в корне репозитория." /></span>
          <input
            value={subdirectory}
            placeholder="Например: homework"
            onChange={(event) => setSubdirectory(event.target.value)}
          />
        </label>
      </details>
    </form>
  );
}

function Stat({ label, value, help }: { label: string; value: number; help: string }) {
  return (
    <article className="stat-card">
      <span>{label} <InfoTip text={help} /></span>
      <strong>{value}</strong>
    </article>
  );
}

function ReviewerView({
  reviewers,
  submissions,
  selected,
  onOpen,
  onRefresh,
  onError
}: {
  reviewers: Reviewer[];
  submissions: Submission[];
  selected: Submission | null;
  onOpen: (id: number) => Promise<Submission>;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [reviewerId, setReviewerId] = useState(reviewers[0]?.id ?? 0);
  useEffect(() => {
    if (selected?.reviewer?.id) setReviewerId(selected.reviewer.id);
  }, [selected?.id, selected?.reviewer?.id]);
  const queue = submissions.filter(
    (item) => item.status !== "approved" && item.reviewer?.id === reviewerId
  );
  const visibleSelected = selected?.reviewer?.id === reviewerId ? selected : null;
  return (
    <main className="review-layout">
      <aside className="queue-panel">
        <h2>Очередь ревьюера</h2>
        <label className="reviewer-select">
          <span className="field-label">Ревьюер <InfoTip text="В демоверсии профиль выбирается вручную. В рабочей системе он определяется после входа." /></span>
          <select value={reviewerId} onChange={(event) => setReviewerId(Number(event.target.value))}>
            {reviewers.map((reviewer) => (
              <option value={reviewer.id} key={reviewer.id}>{reviewer.name}</option>
            ))}
          </select>
        </label>
        <p className="aside-copy">Назначенные работы без подтверждённого результата: {queue.length}</p>
        <div className="queue-list">
          {queue.length === 0 && <p className="muted">Назначенные работы отсутствуют.</p>}
          {queue.map((item) => (
            <button
              type="button"
              className={visibleSelected?.id === item.id ? "queue-item active" : "queue-item"}
              key={item.id}
              onClick={() => onOpen(item.id).catch((error: Error) => onError(error.message))}
            >
              <strong>{studentNameFor(item)}</strong>
              <span>Отправка #{item.id} · {formatDate(item.due_at)}</span>
              <StatusBadge status={item.status} />
            </button>
          ))}
        </div>
      </aside>
      <section className="review-content">
        {!visibleSelected ? (
          <div className="empty-state tall">
            <strong>Работа не выбрана</strong>
            <span>Выберите запись из назначенной очереди.</span>
          </div>
        ) : visibleSelected.status === "processing" || visibleSelected.status === "assigned" ? (
          <div className="processing-state">
            <div className="spinner" />
            <h1>Предварительная проверка выполняется</h1>
            <p>Система фиксирует версию репозитория и проверяет критерии.</p>
          </div>
        ) : visibleSelected.status === "error" ? (
          <div className="error-state">
            <h1>Проверка не завершилась</h1>
            <p>{visibleSelected.error_message}</p>
          </div>
        ) : (
          <ReviewDetail item={visibleSelected} onRefresh={onRefresh} onError={onError} />
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
  const [reviewTab, setReviewTab] = useState<"code" | "criteria">("code");
  const [requestedFile, setRequestedFile] = useState<string | null>(null);
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
          <p className="eyebrow">{activeHomework.code} · Отправка #{item.id}</p>
          <h1>{studentNameFor(item)}</h1>
          <p className="review-assignment">{activeHomework.title}</p>
          <a href={item.source_url} target="_blank" rel="noreferrer">Открыть зафиксированную версию в GitHub ↗</a>
        </div>
        <div className="review-total">
          <span>Предварительный результат <InfoTip text="Сумма предложенных баллов только по оценённым критериям. Итог определяет ревьюер." /></span>
          <strong>{item.suggested_points ?? 0}/{item.assessed_points ?? 0}</strong>
          <small>{item.unresolved_criteria} требуют решения</small>
        </div>
      </div>

      <nav className="content-tabs review-tabs" aria-label="Рабочая область ревьюера">
        <button type="button" className={reviewTab === "code" ? "active" : ""} onClick={() => setReviewTab("code")}>Код и комментарии</button>
        <button type="button" className={reviewTab === "criteria" ? "active" : ""} onClick={() => setReviewTab("criteria")}>Критерии и результат</button>
      </nav>

      <div hidden={reviewTab !== "code"}>
        <CodeReviewPanel
          item={item}
          requestedFile={requestedFile}
          onRefresh={onRefresh}
          onError={onError}
        />
      </div>
      <div hidden={reviewTab !== "criteria"}>
          <div className="responsibility-note">
            Результат не опубликован. Проверьте критерии без оценки, при необходимости измените предложенные баллы и подтвердите итог.
          </div>

          {item.execution_check && (
            <section className="execution-summary">
              <div>
                <p className="eyebrow">Проверка запуска</p>
                <h2>Go {item.execution_check.go_version}</h2>
              </div>
              <div><span>Сборка</span><strong>{item.execution_check.tests_ok ? "Успешно" : "Ошибка"}</strong></div>
              <div><span>go vet</span><strong>{item.execution_check.vet_ok ? "Успешно" : "Ошибка"}</strong></div>
              <div><span>Тесты</span><strong>{item.execution_check.has_tests ? "Найдены" : "Нет в проекте"}</strong></div>
              <div><span>Время</span><strong>{item.execution_check.duration_seconds?.toFixed(1)} с</strong></div>
            </section>
          )}

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
                    <ul className="evidence-list">
                      {criterion.evidence.map((evidence) => (
                        <li key={evidence}>
                          <button
                            type="button"
                            onClick={() => {
                              setRequestedFile(evidence);
                              setReviewTab("code");
                            }}
                          >
                            {evidence}
                          </button>
                        </li>
                      ))}
                    </ul>
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
                    {criterion.status === "needs_human" ? "Ручная проверка" : criterion.status === "pass" ? "Выполнен" : "Не выполнен"}
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

      {item.ai_usage_signal.reasons.length > 0 && <section className="ai-signal">
        <div>
          <p className="eyebrow">Дополнительная проверка</p>
          <h2>Признаки использования генеративного ИИ</h2>
          <p className="signal-result">Обнаружены основания для ручной проверки.</p>
          <p>{item.ai_usage_signal.limitations}</p>
          <ul>
            {item.ai_usage_signal.reasons.map((reason) => (
              <li key={`${reason.description}-${reason.evidence_refs.join("-")}`}>
                {reason.description}
              </li>
            ))}
          </ul>
        </div>
        <span className="status status-human">{signalLabel}</span>
      </section>}

      <div className="review-actions">
        <a className="secondary button-link" href={`/api/submissions/${item.id}/export.xlsx`}>Скачать Excel</a>
        <button className="primary" type="button" onClick={approve} disabled={item.unresolved_criteria > 0 || item.status === "approved"}>
          {item.status === "approved" ? "Результат подтверждён" : "Подтвердить результат"}
        </button>
      </div>
      </div>
    </div>
  );
}

function CodeReviewPanel({
  item,
  requestedFile,
  onRefresh,
  onError
}: {
  item: Submission;
  requestedFile: string | null;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [repository, setRepository] = useState<RepositoryFiles | null>(() => repositoryFilesCache.get(item.id) ?? null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(!repositoryFilesCache.has(item.id));
  const [draftLine, setDraftLine] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const cached = repositoryFilesCache.get(item.id);
    if (cached) {
      setRepository(cached);
      setSelectedPath((current) => {
        if (requestedFile && cached.files.some((file) => file.path === requestedFile)) return requestedFile;
        if (current && cached.files.some((file) => file.path === current)) return current;
        return defaultCodePath(cached.files);
      });
      setLoading(false);
      return () => { cancelled = true; };
    }
    setLoading(true);
    setRepository(null);
    request<RepositoryFiles>(`/api/submissions/${item.id}/files`)
      .then((data) => {
        if (cancelled) return;
        repositoryFilesCache.set(item.id, data);
        setRepository(data);
        setSelectedPath((current) => {
          if (requestedFile && data.files.some((file) => file.path === requestedFile)) return requestedFile;
          if (current && data.files.some((file) => file.path === current)) return current;
          return defaultCodePath(data.files);
        });
      })
      .catch((error: Error) => {
        if (!cancelled) onError(error.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [item.id, onError]);

  useEffect(() => {
    if (requestedFile && repository?.files.some((file) => file.path === requestedFile)) {
      setSelectedPath(requestedFile);
    }
  }, [repository, requestedFile]);

  const selectedFile = repository?.files.find((file) => file.path === selectedPath) ?? null;
  const comments = item.code_comments.filter((comment) => comment.file_path === selectedPath);

  const saveComment = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedPath || !draftLine || !draft.trim()) return;
    setSaving(true);
    try {
      await request(`/api/submissions/${item.id}/comments`, {
        method: "POST",
        body: JSON.stringify({ file_path: selectedPath, line_number: draftLine, body: draft.trim() })
      });
      setDraft("");
      setDraftLine(null);
      await onRefresh();
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="code-loading"><div className="spinner" /><span>Загрузка зафиксированной версии кода…</span></div>;
  }
  if (!repository || repository.files.length === 0) {
    return <div className="empty-state tall"><strong>Файлы для просмотра не найдены</strong><span>Откройте зафиксированную версию в GitHub.</span></div>;
  }

  return (
    <section className="code-review-panel">
      <aside className="file-browser">
        <div className="file-browser-heading">
          <strong>Файлы</strong>
          <span>{repository.files.length}</span>
        </div>
        <div className="file-list">
          {repository.files.map((file) => (
            <button
              type="button"
              className={file.path === selectedPath ? "active" : ""}
              key={file.path}
              title={file.path}
              onClick={() => {
                setSelectedPath(file.path);
                setDraftLine(null);
              }}
            >
              <span>{file.path.split("/").at(-1)}</span>
              <small>{file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/")) : "корень"}</small>
            </button>
          ))}
        </div>
      </aside>
      <div className="code-workspace">
        {selectedFile && (
          <>
            <header className="code-file-heading">
              <div><strong>{selectedFile.path}</strong><span>commit {repository.commit_sha.slice(0, 8)}</span></div>
              <a href={selectedFile.url} target="_blank" rel="noreferrer">Открыть файл в GitHub ↗</a>
            </header>
            <div className="code-lines" role="table" aria-label={`Код файла ${selectedFile.path}`}>
              {selectedFile.content.split("\n").map((line, index) => {
                const lineNumber = index + 1;
                const lineComments = comments.filter((comment) => comment.line_number === lineNumber);
                return (
                  <React.Fragment key={lineNumber}>
                    <button
                      type="button"
                      className={draftLine === lineNumber ? "code-line selected" : "code-line"}
                      onClick={() => {
                        setDraftLine(lineNumber);
                        setDraft("");
                      }}
                      aria-label={`Добавить комментарий к строке ${lineNumber}`}
                    >
                      <span className="line-number">{lineNumber}</span>
                      <code>{line || " "}</code>
                    </button>
                    {lineComments.map((comment) => (
                      <div className="inline-comment" key={comment.id}>
                        <span>Ревьюер · строка {comment.line_number}</span>
                        <p>{comment.body}</p>
                      </div>
                    ))}
                    {draftLine === lineNumber && (
                      <form className="inline-comment-form" onSubmit={saveComment}>
                        <label>
                          Комментарий к строке {lineNumber}
                          <textarea autoFocus value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Что нужно изменить и почему" />
                        </label>
                        <div>
                          <button className="secondary" type="button" onClick={() => setDraftLine(null)}>Отмена</button>
                          <button className="primary" type="submit" disabled={!draft.trim() || saving}>{saving ? "Сохранение…" : "Добавить комментарий"}</button>
                        </div>
                      </form>
                    )}
                  </React.Fragment>
                );
              })}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function StudentView({
  submissions,
  selected,
  onOpen,
  onCreated,
  onError
}: {
  submissions: Submission[];
  selected: Submission | null;
  onOpen: (id: number) => Promise<Submission>;
  onCreated: (item: Submission) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [studentName, setStudentName] = useState("");
  const [assignmentTab, setAssignmentTab] = useState<"brief" | "rubric">("brief");
  const [rubric, setRubric] = useState<RubricResponse | null>(null);
  useEffect(() => {
    request<RubricResponse>("/api/rubric")
      .then(setRubric)
      .catch((error: Error) => onError(error.message));
  }, [onError]);
  const normalizedName = studentName.trim().toLocaleLowerCase("ru-RU");
  const studentSubmissions = normalizedName
    ? submissions.filter((submission) => studentNameFor(submission).toLocaleLowerCase("ru-RU") === normalizedName)
    : [];
  const item = selected && studentSubmissions.some((submission) => submission.id === selected.id)
    ? selected
    : null;
  return (
    <main className="student-page">
      <section className="assignment-detail surface">
        <div className="assignment-overview">
          <p className="context-line">{activeHomework.course} · {activeHomework.code}</p>
          <h1>{activeHomework.title}</h1>
          <p className="assignment-description">{activeHomework.summary}</p>
          <div className="assignment-properties">
            <div>
              <span>Срок сдачи <InfoTip text="После указанного времени работа считается отправленной с опозданием." /></span>
              <strong>{activeHomework.deadline}</strong>
            </div>
            <div>
              <span>Максимальный балл <InfoTip text="Сумма максимальных баллов по всем критериям." /></span>
              <strong>100</strong>
            </div>
            <div>
              <span>Способ сдачи <InfoTip text="Допускается ссылка на репозиторий или Pull Request в GitHub." /></span>
              <strong>GitHub</strong>
            </div>
            <div>
              <span>Итоговое решение <InfoTip text="Система формирует предварительный результат; итог подтверждает назначенный ревьюер." /></span>
              <strong>Ревьюер</strong>
            </div>
          </div>
        </div>
        <nav className="content-tabs" aria-label="Материалы домашней работы">
          <button type="button" className={assignmentTab === "brief" ? "active" : ""} onClick={() => setAssignmentTab("brief")}>Условие</button>
          <button type="button" className={assignmentTab === "rubric" ? "active" : ""} onClick={() => setAssignmentTab("rubric")}>Критерии оценки</button>
        </nav>
        {assignmentTab === "brief" ? (
          <div className="assignment-condition">
            <section className="submission-requirements">
              <h2>Формат сдачи</h2>
              <p>Передайте ссылку на публичный GitHub-репозиторий или Pull Request. Если решение находится не в корне репозитория, укажите путь к каталогу. Система зафиксирует конкретный commit для проверки.</p>
            </section>
            <div className="assignment-stages">
              {activeHomework.stages.map((stage) => (
                <article key={stage.title}>
                  <h2>{stage.title}</h2>
                  <p>{stage.objective}</p>
                  <h3>Требования</h3>
                  <ul>{stage.requirements.map((requirement) => <li key={requirement}>{requirement}</li>)}</ul>
                </article>
              ))}
            </div>
          </div>
        ) : (
          <div className="rubric-full">
            <div className="rubric-summary">
              <h2>Шкала оценки</h2>
              <strong>{rubric?.total_points ?? 100} баллов</strong>
              <p>Качественные критерии без достаточных данных передаются ревьюеру без автоматического балла.</p>
            </div>
            {Array.from(new Set(rubric?.criteria.map((criterion) => criterion.section) ?? [])).map((section) => (
              <section key={section}>
                <h2>{section}</h2>
                {rubric?.criteria.filter((criterion) => criterion.section === section).map((criterion) => (
                  <div className="rubric-row" key={criterion.code}>
                    <span>{criterion.title}</span><strong>{criterion.max_points}</strong>
                  </div>
                ))}
              </section>
            ))}
          </div>
        )}
      </section>
      <section className="surface student-submit">
        <div className="section-heading">
          <div>
            <h2>Сдача работы</h2>
            <p>Укажите имя и ссылку на репозиторий. После отправки система зафиксирует текущий коммит и создаст запись на проверку.</p>
          </div>
        </div>
        <GitHubSubmissionForm
          studentName={studentName}
          onStudentNameChange={setStudentName}
          onCreated={onCreated}
          onError={onError}
        />
      </section>
      <div className="student-grid">
        <aside className="surface student-list">
          <h2>Мои отправки</h2>
          {!normalizedName && <p className="muted">Укажите имя в форме сдачи, чтобы отобразить связанные работы.</p>}
          {normalizedName && studentSubmissions.length === 0 && <p className="muted">Связанные работы отсутствуют.</p>}
          {studentSubmissions.map((submission) => (
            <button type="button" key={submission.id} onClick={() => onOpen(submission.id).catch((error: Error) => onError(error.message))}>
              <span>
                <strong>Отправка #{submission.id}</strong>
                <small>{formatDate(submission.created_at)}</small>
              </span>
              <StatusBadge status={submission.status} />
            </button>
          ))}
        </aside>
        <section className="surface student-result">
          {!item ? (
            <div className="empty-state tall">
              <strong>Работа не выбрана</strong>
              <span>Выберите отправленную работу для просмотра статуса.</span>
            </div>
          ) : item.status !== "approved" ? (
            <div className="student-progress">
              <p className="eyebrow">Отправка #{item.id}</p>
              <h2>{activeHomework.title}</h2>
              <StatusBadge status={item.status} />
              <dl>
                <div><dt>Ревьюер</dt><dd>{item.reviewer?.name ?? "Назначается"}</dd></div>
                <div><dt>Срок проверки</dt><dd>{formatDate(item.due_at)}</dd></div>
                <div><dt>Версия <InfoTip text="Коммит GitHub, зафиксированный системой при отправке." /></dt><dd>{item.commit_sha ? item.commit_sha.slice(0, 8) : "Фиксируется"}</dd></div>
                <div><dt>Источник</dt><dd><a href={item.source_url} target="_blank" rel="noreferrer">Зафиксированная версия ↗</a></dd></div>
              </dl>
              <p className="muted">Итоговый результат будет доступен после подтверждения ревьюером.</p>
            </div>
          ) : (
            <>
              <p className="eyebrow">Итог</p>
              <h2>{activeHomework.title}</h2>
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
