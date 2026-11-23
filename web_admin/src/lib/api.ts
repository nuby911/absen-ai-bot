export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"
).replace(/\/+$/, "");

export const API_ORIGIN = API_BASE_URL.replace(/\/api\/v1$/, "");

const TOKEN_STORAGE_KEY = "smartschool_admin_token";
const USER_STORAGE_KEY = "smartschool_admin_user";

export interface UserProfile {
  id: string;
  name: string;
  email: string;
  role: string;
  nip: string | null;
  has_kiosk_pin: boolean;
}

export interface LoginRequest {
  identifier: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: UserProfile;
}

export interface SchoolClass {
  id: string;
  name: string;
  homeroom_teacher_id: string | null;
  homeroom_teacher_name: string | null;
  student_count: number;
  created_at: string;
}

export interface SchoolClassCreate {
  name: string;
  homeroom_teacher_id?: string | null;
}

export interface SchoolClassUpdate {
  name?: string;
  homeroom_teacher_id?: string | null;
}

export interface Parent {
  id: string;
  name: string;
  phone_wa: string;
  created_at: string;
}

export interface ParentCreate {
  name: string;
  phone_wa: string;
}

export interface ParentUpdate {
  name?: string;
  phone_wa?: string;
}

export interface Student {
  id: string;
  nis: string;
  name: string;
  class_id: string;
  class_name: string;
  parent_id: string;
  parent_name: string;
  parent_phone_wa: string;
  is_active: boolean;
  face_count: number;
  created_at: string;
}

export interface StudentCreate {
  nis: string;
  name: string;
  class_id: string;
  parent_id: string;
  is_active?: boolean;
}

export interface StudentUpdate {
  nis?: string;
  name?: string;
  class_id?: string;
  parent_id?: string;
  is_active?: boolean;
}

export interface Schedule {
  id: string;
  class_id: string;
  class_name: string;
  teacher_id: string;
  teacher_name: string;
  subject_name: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
  late_tolerance_minutes: number;
}

export interface ScheduleCreate {
  class_id: string;
  teacher_id: string;
  subject_name: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
  late_tolerance_minutes?: number;
}

export interface ScheduleUpdate {
  class_id?: string;
  teacher_id?: string;
  subject_name?: string;
  day_of_week?: number;
  start_time?: string;
  end_time?: string;
  late_tolerance_minutes?: number;
}

export interface FaceEmbedding {
  id: string;
  student_id: string;
  image_path: string;
  image_url: string;
  quality_score: number;
  embedding_dim: number;
  created_at: string;
}

export interface FaceThresholdResponse {
  threshold: number;
}

export interface FaceLogLabelRequest {
  actual_student_id: string | null;
  is_impostor: boolean;
  condition_note?: string | null;
}

export interface FaceRecognitionLogItem {
  id: string;
  session_id: string | null;
  predicted_student_id: string | null;
  predicted_student_name: string | null;
  actual_student_id: string | null;
  actual_student_name: string | null;
  top_similarity_score: number;
  threshold_used: number;
  liveness_passed: boolean;
  is_match: boolean;
  latency_ms: number;
  condition_note: string | null;
  is_impostor: boolean;
  classification: "TP" | "FP" | "FN" | "TN" | "unlabeled" | string;
  created_at: string;
}

export interface FaceEvaluationMetrics {
  total_scans: number;
  total_labeled: number;
  tp: number;
  fp: number;
  fn: number;
  tn: number;
  accuracy: number;
  far: number;
  frr: number;
  avg_scan_latency_ms: number;
  threshold: number;
}

export interface ChatbotLogItem {
  id: string;
  created_at: string;
  phone_wa: string;
  user_message: string;
  detected_intent: string | null;
  tool_called: string | null;
  is_in_domain: boolean;
  is_fallback: boolean;
  latency_ms: number;
}

export interface ChatbotEvaluationMetrics {
  total_messages: number;
  in_domain_count: number;
  in_domain_rate: number;
  fallback_count: number;
  fallback_rate: number;
  avg_latency_ms: number;
  recent_logs: ChatbotLogItem[];
}

export interface ClassDailyRecap {
  class_id: string;
  class_name: string;
  homeroom_teacher_name: string | null;
  present_count: number;
  late_count: number;
  permit_or_sick_count: number;
  absent_count: number;
  wa_sent_count: number;
  wa_total_count: number;
}

export interface EvaluationDashboardResponse {
  recap_date: string;
  face_metrics: FaceEvaluationMetrics;
  chatbot_metrics: ChatbotEvaluationMetrics;
  class_recaps: ClassDailyRecap[];
  recent_face_logs: FaceRecognitionLogItem[];
}

export interface LeaveRequestItem {
  id: string;
  student_id: string;
  student_name: string;
  student_nis: string;
  class_id: string;
  class_name: string;
  parent_id: string;
  parent_name: string;
  parent_phone_wa: string;
  request_type: string;
  start_date: string;
  end_date: string;
  reason: string;
  attachment_url: string | null;
  status: string;
  verified_by: string | null;
  verified_by_name: string | null;
  verified_at: string | null;
  created_at: string;
}

export class ApiError extends Error {
  status: number;
  detail?: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function getStoredUser(): UserProfile | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(USER_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as UserProfile;
  } catch {
    return null;
  }
}

export function setAuthSession(token: string, user: UserProfile): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  window.localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
}

export function clearAuthSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  window.localStorage.removeItem(USER_STORAGE_KEY);
}

export function resolveAssetUrl(pathOrUrl: string | null | undefined): string | null {
  if (!pathOrUrl) return null;
  if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) {
    return pathOrUrl;
  }
  const normalized = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${API_ORIGIN}${normalized}`;
}

function extractErrorMessage(payload: unknown, fallbackStatus: number): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const messages = detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return typeof item === "string" ? item : "";
        })
        .filter(Boolean);
      if (messages.length > 0) {
        return messages.join("; ");
      }
    }
  }
  if (fallbackStatus === 401) {
    return "Sesi Anda telah berakhir. Silakan masuk kembali.";
  }
  if (fallbackStatus === 403) {
    return "Akses ditolak. Fitur ini hanya tersedia untuk Admin Sekolah.";
  }
  if (fallbackStatus === 404) {
    return "Data yang diminta tidak ditemukan.";
  }
  return `Permintaan gagal dengan kode status ${fallbackStatus}.`;
}

let unauthorizedHandler: (() => void) | null = null;

export function registerUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function redirectToLoginOnUnauthorized(): void {
  clearAuthSession();
  if (
    typeof window !== "undefined" &&
    window.location.pathname !== "/login" &&
    unauthorizedHandler
  ) {
    unauthorizedHandler();
  }
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  skipAuthRedirect?: boolean;
}

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, headers: customHeaders, skipAuthRedirect = false, ...init } = options;

  const headers = new Headers(customHeaders);
  const token = getAccessToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let preparedBody: BodyInit | undefined;
  if (body instanceof FormData) {
    preparedBody = body;
  } else if (body !== undefined) {
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    preparedBody = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      body: preparedBody,
    });
  } catch {
    throw new ApiError(
      0,
      "Tidak dapat terhubung ke server backend. Pastikan API FastAPI sedang berjalan."
    );
  }

  if (response.status === 401 && !skipAuthRedirect) {
    redirectToLoginOnUnauthorized();
    throw new ApiError(401, "Sesi Anda telah berakhir. Mengalihkan ke halaman login...");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") || "";
  let parsedBody: unknown = null;
  if (contentType.includes("application/json")) {
    try {
      parsedBody = await response.json();
    } catch {
      parsedBody = null;
    }
  } else {
    const text = await response.text();
    parsedBody = text || null;
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      extractErrorMessage(parsedBody, response.status),
      parsedBody
    );
  }

  return parsedBody as T;
}

// ---------------------------------------------------------------------------
// Auth API
// ---------------------------------------------------------------------------

export async function loginAdmin(payload: LoginRequest): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: payload,
    skipAuthRedirect: true,
  });
}

export async function getMe(): Promise<UserProfile> {
  return apiRequest<UserProfile>("/auth/me", { method: "GET" });
}

// ---------------------------------------------------------------------------
// Master Data API: Classes, Parents, Students, Schedules
// ---------------------------------------------------------------------------

export async function getClasses(): Promise<SchoolClass[]> {
  return apiRequest<SchoolClass[]>("/classes", { method: "GET" });
}

export async function createClass(payload: SchoolClassCreate): Promise<SchoolClass> {
  return apiRequest<SchoolClass>("/classes", {
    method: "POST",
    body: payload,
  });
}

export async function updateClass(
  classId: string,
  payload: SchoolClassUpdate
): Promise<SchoolClass> {
  return apiRequest<SchoolClass>(`/classes/${encodeURIComponent(classId)}`, {
    method: "PUT",
    body: payload,
  });
}

export async function deleteClass(classId: string): Promise<void> {
  return apiRequest<void>(`/classes/${encodeURIComponent(classId)}`, {
    method: "DELETE",
  });
}

export async function getParents(): Promise<Parent[]> {
  return apiRequest<Parent[]>("/parents", { method: "GET" });
}

export async function createParent(payload: ParentCreate): Promise<Parent> {
  return apiRequest<Parent>("/parents", {
    method: "POST",
    body: payload,
  });
}

export async function updateParent(
  parentId: string,
  payload: ParentUpdate
): Promise<Parent> {
  return apiRequest<Parent>(`/parents/${encodeURIComponent(parentId)}`, {
    method: "PUT",
    body: payload,
  });
}

export async function deleteParent(parentId: string): Promise<void> {
  return apiRequest<void>(`/parents/${encodeURIComponent(parentId)}`, {
    method: "DELETE",
  });
}

export async function getStudents(classId?: string): Promise<Student[]> {
  const qs = classId ? `?class_id=${encodeURIComponent(classId)}` : "";
  return apiRequest<Student[]>(`/students${qs}`, { method: "GET" });
}

export async function createStudent(payload: StudentCreate): Promise<Student> {
  return apiRequest<Student>("/students", {
    method: "POST",
    body: payload,
  });
}

export async function updateStudent(
  studentId: string,
  payload: StudentUpdate
): Promise<Student> {
  return apiRequest<Student>(`/students/${encodeURIComponent(studentId)}`, {
    method: "PUT",
    body: payload,
  });
}

export async function deleteStudent(studentId: string): Promise<void> {
  return apiRequest<void>(`/students/${encodeURIComponent(studentId)}`, {
    method: "DELETE",
  });
}

export async function getSchedules(filters?: {
  class_id?: string;
  teacher_id?: string;
  day_of_week?: number;
}): Promise<Schedule[]> {
  const params = new URLSearchParams();
  if (filters?.class_id) params.set("class_id", filters.class_id);
  if (filters?.teacher_id) params.set("teacher_id", filters.teacher_id);
  if (filters?.day_of_week !== undefined) {
    params.set("day_of_week", String(filters.day_of_week));
  }
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<Schedule[]>(`/schedules${qs}`, { method: "GET" });
}

export async function createSchedule(payload: ScheduleCreate): Promise<Schedule> {
  return apiRequest<Schedule>("/schedules", {
    method: "POST",
    body: payload,
  });
}

export async function updateSchedule(
  scheduleId: string,
  payload: ScheduleUpdate
): Promise<Schedule> {
  return apiRequest<Schedule>(`/schedules/${encodeURIComponent(scheduleId)}`, {
    method: "PUT",
    body: payload,
  });
}

export async function deleteSchedule(scheduleId: string): Promise<void> {
  return apiRequest<void>(`/schedules/${encodeURIComponent(scheduleId)}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Face Dataset API (Screen 10)
// ---------------------------------------------------------------------------

export async function getStudentFaces(studentId: string): Promise<FaceEmbedding[]> {
  return apiRequest<FaceEmbedding[]>(
    `/students/${encodeURIComponent(studentId)}/faces`,
    { method: "GET" }
  );
}

export async function uploadStudentFace(
  studentId: string,
  file: Blob,
  filename = "face-capture.jpg"
): Promise<FaceEmbedding> {
  const formData = new FormData();
  formData.append("file", file, filename);
  return apiRequest<FaceEmbedding>(
    `/students/${encodeURIComponent(studentId)}/faces`,
    {
      method: "POST",
      body: formData,
    }
  );
}

export async function deleteStudentFace(
  studentId: string,
  faceId: string
): Promise<void> {
  return apiRequest<void>(
    `/students/${encodeURIComponent(studentId)}/faces/${encodeURIComponent(faceId)}`,
    { method: "DELETE" }
  );
}

// ---------------------------------------------------------------------------
// Evaluation, Threshold & Reports API (Screen 11)
// ---------------------------------------------------------------------------

export async function getFaceThreshold(): Promise<FaceThresholdResponse> {
  return apiRequest<FaceThresholdResponse>("/settings/face-threshold", {
    method: "GET",
  });
}

export async function updateFaceThreshold(
  threshold: number
): Promise<FaceThresholdResponse> {
  return apiRequest<FaceThresholdResponse>("/settings/face-threshold", {
    method: "PUT",
    body: { threshold },
  });
}

export async function getEvaluationMetrics(
  recapDate?: string
): Promise<EvaluationDashboardResponse> {
  const qs = recapDate ? `?recap_date=${encodeURIComponent(recapDate)}` : "";
  return apiRequest<EvaluationDashboardResponse>(`/evaluation/metrics${qs}`, {
    method: "GET",
  });
}

export async function labelFaceLog(
  logId: string,
  payload: FaceLogLabelRequest
): Promise<FaceRecognitionLogItem> {
  return apiRequest<FaceRecognitionLogItem>(
    `/evaluation/face-logs/${encodeURIComponent(logId)}/label`,
    {
      method: "POST",
      body: payload,
    }
  );
}

export async function downloadAttendanceCsv(filters?: {
  class_id?: string;
  start_date?: string;
  end_date?: string;
}): Promise<void> {
  const params = new URLSearchParams();
  if (filters?.class_id) params.set("class_id", filters.class_id);
  if (filters?.start_date) params.set("start_date", filters.start_date);
  if (filters?.end_date) params.set("end_date", filters.end_date);
  const qs = params.toString() ? `?${params.toString()}` : "";

  const headers = new Headers();
  const token = getAccessToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/reports/attendance.csv${qs}`, {
      method: "GET",
      headers,
    });
  } catch {
    throw new ApiError(
      0,
      "Tidak dapat mengunduh laporan CSV. Pastikan backend aktif."
    );
  }

  if (response.status === 401) {
    redirectToLoginOnUnauthorized();
    throw new ApiError(401, "Sesi Anda telah berakhir.");
  }

  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      parsed = null;
    }
    throw new ApiError(
      response.status,
      extractErrorMessage(parsed, response.status),
      parsed
    );
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filters?.start_date
    ? `rekap-absensi-${filters.start_date}.csv`
    : "rekap-absensi.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

export async function getLeaveRequests(
  statusFilter?: "pending" | "approved" | "rejected"
): Promise<LeaveRequestItem[]> {
  const qs = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
  return apiRequest<LeaveRequestItem[]>(`/leave-requests${qs}`, {
    method: "GET",
  });
}
