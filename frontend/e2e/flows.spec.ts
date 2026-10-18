// T-20(PC·모바일·키보드·IME·출처 포커스)와 T-21(확인 반복·유실·만료·로그아웃 캐시). 서버 상태를 직접 확인한다.
import { expect, test, type Page } from "@playwright/test";

// 데모 시드 계정(backend/src/agent/modules/identity_access/demo_org.json, 가상 계정).
const ACCOUNTS = {
  sales: { username: "emp-sales", password: "demo-emp-sales-1017" },
  dev: { username: "emp-dev", password: "demo-emp-dev-1017" },
};

async function login(page: Page, who: keyof typeof ACCOUNTS = "sales") {
  await page.goto("/");
  await page.getByLabel("아이디").fill(ACCOUNTS[who].username);
  await page.getByLabel("비밀번호").fill(ACCOUNTS[who].password);
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page.getByLabel("질문")).toBeVisible(); // 모바일에서는 로그아웃이 접힌 메뉴 안에 있다
}

async function ask(page: Page, text: string) {
  await page.getByLabel("질문").fill(text);
  await page.getByLabel("질문").press("Enter");
  await expect(page.locator(".composer")).toHaveAttribute("aria-busy", "false");
}

/** 지정한 경로로 나간 쓰기 요청을 센다(화면이 아니라 실제로 보낸 요청 수로 확인). */
function countRequests(page: Page, pattern: RegExp): { count: number; keys: string[] } {
  const seen = { count: 0, keys: [] as string[] };
  page.on("request", (request) => {
    if (request.method() === "POST" && pattern.test(request.url())) {
      seen.count += 1;
      seen.keys.push(request.headers()["idempotency-key"] ?? "");
    }
  });
  return seen;
}

async function tickets(page: Page): Promise<number> {
  const response = await page.request.get("/api/v1/it-tickets");
  return (await response.json()).total;
}

test("교육 질문: 진행 단계 후 결과를 한 번에, 상세는 Esc로 닫고 포커스를 돌려준다", async ({ page }) => {
  await login(page);
  // 화면에 나타난 진행 문구를 모두 기록한다(빠르게 지나가도 놓치지 않게).
  await page.evaluate(() => {
    const seen: string[] = [];
    (window as unknown as { stages: string[] }).stages = seen;
    new MutationObserver(() => {
      const text = document.querySelector(".progress")?.textContent;
      if (text && seen[seen.length - 1] !== text) seen.push(text);
    }).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  // 실제 스트림을 바꾸지 않고 복제해 받은 SSE 본문을 기록한다.
  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    const log = { body: "" };
    (window as unknown as { sse: typeof log }).sse = log;
    window.fetch = async (input, init) => {
      const response = await original(input, init);
      if (String(input).endsWith("/messages") && init?.method === "POST" && response.body) {
        const [mine, theirs] = response.body.tee();
        void new Response(mine).text().then((text) => (log.body = text));
        return new Response(theirs, { status: response.status, headers: response.headers });
      }
      return response;
    };
  });
  await page.getByLabel("질문").fill("다음 주 교육 일정 알려줘");
  await page.getByLabel("질문").press("Enter");
  await expect(page.locator(".composer")).toHaveAttribute("aria-busy", "false");
  await expect.poll(() => page.evaluate(() => (window as unknown as { sse: { body: string } }).sse.body)).toContain("event: result");
  const body = await page.evaluate(() => (window as unknown as { sse: { body: string } }).sse.body);
  expect(body).toContain("event: progress");
  expect(body).toContain('"stage": "training_lookup"');
  expect(body.indexOf("event: result")).toBeGreaterThan(body.lastIndexOf("event: progress"));
  await expect(page.locator(".composer")).toHaveAttribute("aria-busy", "false");
  await expect(page.getByText("다음 주 교육은 2건입니다")).toBeVisible();
  const stages = await page.evaluate(() => (window as unknown as { stages: string[] }).stages);
  // 화면에는 서버가 보낸 단계 라벨만 나온다. 단계가 빨리 바뀌면 일부는 다음 단계에 덮이므로(빠른 기계) 특정
  // 단계 하나를 요구하지 않고, 서버 단계가 하나 이상 표시됐는지 본다. 도구 단계 송신은 위 SSE 본문으로 확인했다.
  const labels = ["요청을 받았습니다", "답변을 준비하는 중", "교육 일정 조회 중", "결과 확인 중"];
  expect(stages.every((s) => s === "처리 중" || labels.includes(s))).toBe(true);
  expect(stages.some((s) => labels.includes(s))).toBe(true);
  // 결과는 진행이 끝난 뒤 한 번에 붙는다(답 문단 1개).
  await expect(page.locator(".message.assistant")).toHaveCount(1);
  const ref = page.getByRole("button", { name: "신입사원 정보보안 교육" });
  await ref.click();
  await expect(page.getByRole("complementary", { name: "상세" })).toContainText("장소");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("complementary", { name: "상세" })).toHaveCount(0);
  await expect(ref).toBeFocused();
});

test("IME: 한글 조합 중 Enter는 보내지 않고, Shift+Enter는 줄바꿈이다", async ({ page }) => {
  await login(page);
  const posts = countRequests(page, /\/conversations(\/[^/]+\/messages)?$/);
  const input = page.getByLabel("질문");
  await input.fill("교육 일정");
  await input.evaluate((el) => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true, isComposing: true }));
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 229, bubbles: true, cancelable: true }));
  });
  await input.press("Shift+Enter");
  await expect(input).toHaveValue("교육 일정\n");
  await page.waitForTimeout(500);
  expect(posts.count).toBe(0); // 대화 생성·메시지 전송 요청이 하나도 나가지 않았다
  await expect(page.locator(".message.user")).toHaveCount(0);
  await input.press("Enter"); // 조합이 끝난 Enter는 보낸다
  await expect(page.locator(".message.user")).toHaveCount(1);
  expect(posts.count).toBe(2); // 대화 생성 1 + 메시지 1
});

test("규정 인용: 판본·종전·적용 기준·쪽을 보여 주고 PDF는 해당 쪽으로 연다", async ({ page }) => {
  await login(page);
  await ask(page, "9월 29일에 시작한 외부교육 한도는?");
  const citation = page.locator("button.citation").first();
  await expect(citation).toContainText("종전");
  await citation.focus();
  await page.keyboard.press("Enter");
  const panel = page.getByRole("complementary", { name: "상세" });
  await expect(panel).toContainText("교육 시작일 기준 2026-09-29");
  await expect(panel).toContainText("연도는 서버가 추론");
  await expect(panel.getByRole("link", { name: /PDF \d+쪽 열기/ })).toHaveAttribute("href", /\/api\/v1\/source-files\/PDF-031\/pdf#page=\d+/);
});

test("IT 접수: 초안 → 수정 저장 → 확인 반복 클릭에도 티켓 1건, 새로고침 뒤 실제 상태", async ({ page }) => {
  await login(page);
  const before = await tickets(page);
  const created = page.waitForResponse((r) => r.url().endsWith("/api/v1/conversations") && r.request().method() === "POST");
  await ask(page, "VPN이 안 돼요. 접수해 주세요");
  const conversationId = String((await (await created).json()).id);
  const card = page.getByRole("region", { name: "IT 지원 접수 확인" }).last();
  await expect(card).toContainText("초안(아직 접수 전)");
  await expect(card).not.toContainText("접수 완료");
  await card.getByRole("button", { name: "내용 수정" }).click();
  const form = card.getByRole("form", { name: "접수 내용 수정" });
  await expect(form.locator('[name="subject"]')).toBeFocused();
  await form.locator('[name="request_type"]').selectOption("incident");
  await form.locator('[name="occurred_at"]').fill("2026-10-16T09:30");
  await form.locator('[name="urgent_work"]').selectOption("false");
  const revises = countRequests(page, /\/ticket-actions\/[^/]+\/revise$/);
  const confirms = countRequests(page, /\/ticket-actions\/[^/]+\/confirm$/);
  await form.getByRole("button", { name: "저장" }).click();
  await expect(card).toContainText("확인 대기(아직 접수 전)");
  expect(revises.count).toBe(1);
  // 바꾼 것 없는 pending 저장은 revise를 보내지 않는다(새 action 없음).
  await card.getByRole("button", { name: "내용 수정" }).click();
  await card.getByRole("form", { name: "접수 내용 수정" }).getByRole("button", { name: "저장" }).click();
  await expect(card).toContainText("확인 대기(아직 접수 전)");
  expect(revises.count).toBe(1);
  const confirm = card.getByRole("button", { name: "확인하고 접수" });
  // 렌더가 버튼을 끄기 전, 같은 틱에 두 번 누른다(가장 빠른 반복 클릭).
  await confirm.evaluate((el: HTMLButtonElement) => {
    el.click();
    el.click();
  });
  await expect(card).toContainText("접수 완료");
  expect(confirms.count).toBe(1); // 두 번째 클릭은 요청을 보내지 않는다(서버 수렴에 기대지 않음)
  expect(await tickets(page)).toBe(before + 1);
  await page.reload();
  await page.locator(`.sidebar li button[data-id="${conversationId}"]`).click();
  await expect(page.getByRole("region", { name: "IT 지원 접수 확인" }).last()).toContainText("접수 완료");
});

test("응답 유실: 확인 응답이 끊겨도 실제 상태를 다시 읽고 중복 접수하지 않는다", async ({ page }) => {
  await login(page);
  const before = await tickets(page);
  await ask(page, "VPN이 또 안 돼요. 접수해 주세요");
  const card = page.getByRole("region", { name: "IT 지원 접수 확인" }).last();
  await card.getByRole("button", { name: "내용 수정" }).click();
  const form = card.getByRole("form", { name: "접수 내용 수정" });
  await form.locator('[name="request_type"]').selectOption("inquiry");
  await form.locator('[name="urgent_work"]').selectOption("false");
  await form.getByRole("button", { name: "저장" }).click();
  await expect(card).toContainText("확인 대기");
  let dropped = false;
  await page.route("**/ticket-actions/*/confirm", async (route) => {
    if (dropped) return route.continue();
    dropped = true;
    await route.fetch(); // 서버에서는 처리됐지만
    await route.abort("connectionreset"); // 응답이 화면에 오지 않았다
  });
  await card.getByRole("button", { name: "확인하고 접수" }).click();
  await expect(card).toContainText("접수 완료"); // GET action으로 실제 상태 확인
  expect(await tickets(page)).toBe(before + 1);
});

test("수정 응답 유실: 저장 응답이 끊겨도 실제 상태를 읽어 저장된 내용을 보여 주고 다시 저장하지 않는다", async ({ page }) => {
  await login(page);
  const before = await tickets(page);
  await ask(page, "VPN 접속이 안 돼요. 접수해 주세요");
  const card = page.getByRole("region", { name: "IT 지원 접수 확인" }).last();
  await card.getByRole("button", { name: "내용 수정" }).click();
  const form = card.getByRole("form", { name: "접수 내용 수정" });
  await form.locator('[name="request_type"]').selectOption("inquiry");
  await form.locator('[name="urgent_work"]').selectOption("false");
  const revises = countRequests(page, /\/ticket-actions\/[^/]+\/revise$/);
  let dropped = false;
  await page.route("**/ticket-actions/*/revise", async (route) => {
    if (dropped) return route.continue();
    dropped = true;
    await route.fetch(); // 서버에서는 저장됐지만
    await route.abort("connectionreset"); // 응답이 오지 않았다
  });
  await form.getByRole("button", { name: "저장" }).click();
  await expect(card).toContainText("확인 대기(아직 접수 전)");
  expect(revises.count).toBe(1);
  await card.getByRole("button", { name: "확인하고 접수" }).click();
  await expect(card).toContainText("접수 완료");
  expect(await tickets(page)).toBe(before + 1);
});

test("저장된 실패: 서버가 실패로 끝낸 요청은 다시 보낼 때 새 키를 쓴다", async ({ page }) => {
  await login(page);
  const sends = countRequests(page, /\/conversations\/[^/]+\/messages$/);
  let failed = false;
  await page.route("**/conversations/*/messages", async (route) => {
    if (route.request().method() !== "POST" || failed) return route.continue();
    failed = true;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "MODEL_UNAVAILABLE", message: "잠시 후 다시 시도해 주세요.", stage: "model", retryable: true, details: null } }),
    });
  });
  await ask(page, "다음 주 교육 일정 알려줘");
  await expect(page.getByRole("alert")).toContainText("잠시 후 다시 시도해 주세요.");
  await page.getByRole("button", { name: "다시 보내기" }).click();
  await expect(page.getByText("다음 주 교육은 2건입니다")).toBeVisible();
  expect(sends.count).toBe(2);
  expect(sends.keys[0]).not.toBe(sends.keys[1]);
});

test("대화 전환: 답을 기다리는 동안 대화를 바꿀 수 없고, 답은 보낸 대화에만 붙는다", async ({ page }) => {
  await login(page);
  const created = page.waitForResponse((r) => r.url().endsWith("/api/v1/conversations") && r.request().method() === "POST");
  await ask(page, "다음 주 교육 일정 알려줘");
  const first = String((await (await created).json()).id);
  await page.getByRole("button", { name: "새 대화" }).click();
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/conversations/*/messages", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await gate;
    await route.continue();
  });
  await page.getByLabel("질문").fill("9월 29일에 시작한 외부교육 한도는?");
  await page.getByLabel("질문").press("Enter");
  await expect(page.locator(".composer")).toHaveAttribute("aria-busy", "true");
  const list = page.locator(".sidebar li button");
  expect(await list.count()).toBeGreaterThanOrEqual(2);
  for (const button of await list.all()) await expect(button).toBeDisabled();
  await expect(page.getByRole("button", { name: "새 대화" })).toBeDisabled();
  release();
  await expect(page.locator(".composer")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator("button.citation").first()).toBeVisible();
  await expect(page.locator(".message")).toHaveCount(2); // 지금 대화에는 이번 질문·답만 있다
  await page.locator(`.sidebar li button[data-id="${first}"]`).click(); // 처음 대화
  await expect(page.getByText("다음 주 교육은 2건입니다")).toBeVisible();
  await expect(page.locator(".message")).toHaveCount(2);
  await expect(page.locator("button.citation")).toHaveCount(0);
});

test("만료: 만료 응답이면 미접수 안내를 보여 주고 접수 완료로 표시하지 않는다", async ({ page }) => {
  await login(page);
  await ask(page, "VPN 연결이 끊겨요. 접수해 주세요");
  const card = page.getByRole("region", { name: "IT 지원 접수 확인" }).last();
  await card.getByRole("button", { name: "내용 수정" }).click();
  const form = card.getByRole("form", { name: "접수 내용 수정" });
  await form.locator('[name="request_type"]').selectOption("inquiry");
  await form.locator('[name="urgent_work"]').selectOption("false");
  await form.getByRole("button", { name: "저장" }).click();
  await page.route("**/ticket-actions/*/confirm", (route) =>
    route.fulfill({
      status: 410,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "ACTION_EXPIRED", message: "만료", stage: "confirmation", retryable: false, details: null } }),
    }),
  );
  await card.getByRole("button", { name: "확인하고 접수" }).click();
  await expect(card).toContainText("만료되어 접수되지 않았습니다");
  await expect(card).not.toContainText("접수 완료");
});

test("로그아웃: 이전 사용자의 대화·인용이 화면에 남지 않는다", async ({ page }) => {
  await login(page, "sales");
  await ask(page, "9월 29일에 시작한 외부교육 한도는?");
  await page.getByRole("button", { name: "로그아웃" }).click();
  await expect(page.getByLabel("아이디")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("외부교육비");
  await login(page, "dev");
  await expect(page.locator(".sidebar li")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("외부교육비");
});

test.describe("모바일", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("목록은 메뉴로 열고, 상세는 전체 너비로 열린 뒤 뒤로 가면 포커스가 돌아온다", async ({ page }) => {
    await login(page);
    await ask(page, "다음 주 교육 일정 알려줘");
    const ref = page.getByRole("button", { name: "신입사원 협업 도구 교육" });
    await ref.click();
    const panel = page.getByRole("complementary", { name: "상세" });
    const box = await panel.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(370);
    await panel.getByRole("button", { name: "뒤로" }).click();
    await expect(ref).toBeFocused();
    await page.getByRole("button", { name: /대화 목록 열기/ }).click();
    await expect(page.getByRole("navigation", { name: "대화 목록" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
