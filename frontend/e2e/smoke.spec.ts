import { expect, test } from "@playwright/test";
import { mockApi, signIn } from "./api";

const JOBS = [
  {
    id: "1", title: "Graduate Software Engineer", company: "Acme Robotics", location: "Cambridge, UK",
    level: "junior", source: "greenhouse", url: "https://jobs.example.com/1",
    sponsorship: "offered", sponsorship_evidence: "We can sponsor Skilled Worker visas.",
    years_min: 0, degree: "required",
  },
  {
    id: "2", title: "Junior Data Engineer", company: "Beta Systems", location: "London, UK",
    level: "junior", source: "lever", url: "https://jobs.example.com/2",
    licensed_sponsor: true, clearance: "SC", years_min: 2, degree: "preferred",
  },
];

const PERSONA = {
  core_info: { first_name: "Sam", last_name: "Okafor", email: "sam@example.com" },
  preferences: { target_titles: [], preferred_locations: [], employment_type: "full-time" },
  diversity: {}, screening: {}, history: [], education: [], projects: [], certifications: [],
  story_bank: [], skills: [], summary: "", custom_directives: "",
};

const app = (id: string, status: string, extra: object = {}) => ({
  id, job_id: `job-${id}`, job_title: `Role ${id}`, company: `Company ${id}`, location: "London",
  job_url: `https://jobs.example.com/${id}`, status, date_applied: null, composite_score: 0, exposure_score: 0.4,
  fit_score: 80, skill_gaps: [], level_match: "strong", notes: "", created_at: new Date().toISOString(), ...extra,
});

/** What every signed-in page asks for: the sidebar reads the persona, the applications, autopilot's runs and the inbox. */
const SHELL = { "GET /api/persona": PERSONA, "GET /api/applications": [], "GET /api/autopilot/runs": [],
                "GET /api/gmail/events": [] };

test("a signed-out visitor is sent to the login page", async ({ page }) => {
  const api = await mockApi(page, {});
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  api.expectAllMocked();
});

test("logging in keeps the token and opens the dashboard", async ({ page }) => {
  let form = "";
  const api = await mockApi(page, {
    ...SHELL,
    "POST /api/login": (request) => {
      form = request.postData() ?? "";
      return { access_token: "fresh-token", token_type: "bearer" };
    },
    "GET /api/onboarding/status": { complete: true },
    "POST /api/score-skills": { skill_risks: [] },
    "GET /api/jobs": { jobs: [], has_more: false, discovering: false, sponsorship: "any" },
  });
  await page.goto("/login");
  await page.getByLabel("Email").fill("sam@example.com");
  await page.getByLabel("Password").fill("correct horse");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Sam");
  expect(form).toContain("sam@example.com");
  expect(await page.evaluate(() => localStorage.getItem("windrush_token"))).toBe("fresh-token");
  api.expectAllMocked();
});

test("a wrong password shows the server's message", async ({ page }) => {
  const api = await mockApi(page, {
    "POST /api/login": { status: 401, json: { detail: "Incorrect email or password" } },
  });
  await page.goto("/login");
  await page.getByLabel("Email").fill("sam@example.com");
  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByText("Incorrect email or password")).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
  api.expectAllMocked();
});

test("the feed shows each job's badges and sends the filters to the API", async ({ page }) => {
  await signIn(page);
  const api = await mockApi(page, {
    ...SHELL,
    // The server picks "possible" for a profile that needs sponsorship and says so.
    "GET /api/jobs": { jobs: JOBS, has_more: false, discovering: false, sponsorship: "possible" },
  });
  await page.goto("/jobs");

  const card = (job: (typeof JOBS)[number]) =>
    page.getByRole("region", { name: "Roles" }).getByRole("button").filter({ hasText: job.title });
  await expect(page.getByText("2 jobs")).toBeVisible();
  for (const text of ["Visa sponsorship", "No experience needed", "Degree required"]) {
    await expect(card(JOBS[0]).getByText(text, { exact: true })).toBeVisible();
  }
  for (const text of ["Licensed sponsor", "SC clearance", "2+ yrs exp"]) {
    await expect(card(JOBS[1]).getByText(text, { exact: true })).toBeVisible();
  }
  await expect(card(JOBS[1]).getByText("Degree required")).toHaveCount(0);   // only preferred

  await expect(page.getByRole("checkbox", { name: "Possible" })).toBeChecked();

  await page.getByLabel("Experience asked").selectOption({ label: "No experience required" });
  await expect.poll(() => api.params("/api/jobs").at(-1)?.get("max_years")).toBe("0");

  await page.getByRole("checkbox", { name: "No degree needed" }).check();
  await expect.poll(() => api.params("/api/jobs").at(-1)?.get("no_degree")).toBe("true");
  expect(api.params("/api/jobs").at(-1)?.get("max_years")).toBe("0");      // filters combine

  await page.getByRole("button", { name: "Clear all" }).click();
  await expect.poll(() => api.params("/api/jobs").at(-1)?.has("no_degree")).toBe(false);
  const last = api.params("/api/jobs").at(-1)!;
  expect([last.has("max_years"), last.has("sponsorship"), last.get("page")]).toEqual([false, false, "1"]);
  api.expectAllMocked();
});

test("an expired session sends you back to the login page", async ({ page }) => {
  const expired = { status: 401, json: { detail: "Could not validate credentials" } };
  const api = await mockApi(page, {
    "GET /api/jobs": expired, "GET /api/persona": expired, "GET /api/applications": expired,
    "GET /api/autopilot/runs": expired, "GET /api/gmail/events": expired,
  });
  await page.goto("/login");
  await page.evaluate(() => localStorage.setItem("windrush_token", "expired-token"));
  await page.goto("/jobs");
  await expect(page).toHaveURL(/\/login$/);
  expect(await page.evaluate(() => localStorage.getItem("windrush_token"))).toBeNull();
  api.expectAllMocked();
});

test("target titles and locations typed with commas are saved as lists", async ({ page }) => {
  await signIn(page);
  let saved: typeof PERSONA | null = null;
  const api = await mockApi(page, {
    ...SHELL,
    "PUT /api/persona": (request) => {
      saved = request.postDataJSON();
      return { status: "ok" };
    },
  });
  await page.goto("/profile");
  await page.getByRole("button", { name: /^Job preferences/ }).click();
  await expect(page).toHaveURL(/#prefs$/);

  // Typed key by key: a comma or a space must survive until the next word is typed.
  await page.getByLabel("Target job titles").pressSequentially("Graduate Software Engineer, Junior ML Engineer");
  await page.getByLabel("Preferred locations").pressSequentially("London, New York");

  // Saved on its own, a moment after the typing stops.
  await expect.poll(() => saved?.preferences.preferred_locations).toEqual(["London", "New York"]);
  expect(saved!.preferences.target_titles).toEqual(["Graduate Software Engineer", "Junior ML Engineer"]);
  expect(saved!.core_info.first_name).toBe("Sam");                       // the rest of the profile is kept
  await expect(page.getByText("All changes saved")).toBeVisible();
  api.expectAllMocked();
});

test("changing a status in the application panel saves it, and Esc closes the panel", async ({ page }) => {
  await signIn(page);
  const patches: unknown[] = [];
  const api = await mockApi(page, {
    ...SHELL,
    "GET /api/applications": [app("a1", "Applied"), app("a2", "Saved")],
    "PATCH /api/applications/a1/status": (request) => {
      patches.push(request.postDataJSON());
      return { updated: true };
    },
  });
  await page.goto("/applications");
  await page.getByRole("button", { name: /Role a1 at Company a1/ }).click();
  const panel = page.getByRole("dialog", { name: "Application details" });
  await expect(panel).toBeVisible();

  await panel.getByLabel("Status").selectOption({ label: "Interview" });
  await expect.poll(() => patches).toEqual([{ status: "Interview" }]);
  await expect(page.getByRole("region", { name: "Interview, 1" })).toBeVisible();   // moved columns

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  api.expectAllMocked();
});

test("the review queue lists paused applications and records one you sent yourself", async ({ page }) => {
  await signIn(page);
  const patches: unknown[] = [];
  const api = await mockApi(page, {
    ...SHELL,
    "GET /api/applications": [app("a1", "Pending Review"), app("a2", "Pending Review"), app("a3", "Applied")],
    "PATCH /api/applications/a1/status": (request) => {
      patches.push(request.postDataJSON());
      return { updated: true };
    },
  });
  await page.goto("/review");
  await expect(page.getByRole("tab")).toHaveCount(2);
  await expect(page.getByRole("link", { name: /Agent review/ })).toContainText("2");      // sidebar badge
  await expect(page.getByRole("heading", { name: "Role a1 · Company a1" })).toBeVisible();

  await page.getByRole("button", { name: "I submitted it myself" }).click();
  await expect.poll(() => patches).toEqual([{ status: "Applied" }]);
  await expect(page.getByRole("heading", { name: "Role a2 · Company a2" })).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(1);
  api.expectAllMocked();
});

test("the theme switch applies dark mode and remembers it", async ({ page }) => {
  await signIn(page);
  const api = await mockApi(page, {
    ...SHELL,
    "GET /api/jobs": { jobs: [], has_more: false, discovering: false, sponsorship: "any" },
  });
  await page.goto("/jobs");
  await page.getByRole("button", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  expect(await page.evaluate(() => localStorage.getItem("windrush_theme"))).toBe("dark");

  await page.reload();
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);       // applied before paint, from storage
  await page.getByRole("button", { name: "Light" }).click();
  await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
  api.expectAllMocked();
});

test("the job workspace tailors a CV and checks it against the persona", async ({ page }) => {
  await signIn(page);
  const job = { ...JOBS[0], description: "Python and FastAPI services on PostgreSQL. Docker a plus." };
  await page.addInitScript((j) => sessionStorage.setItem("job_1", JSON.stringify(j)), job);
  const cv = {
    name: "Sam Okafor", contact: { email: "sam@example.com" }, summary: "Graduate who builds Python services.",
    skills: [{ category: "Backend", items: ["Python", "FastAPI"] }],
    experience: [{ title: "Intern", employer: "Brightwave", bullets: ["Cut latency by 35%."] }],
    education: [], projects: [], certifications: [],
  };
  const checked: unknown[] = [];
  const api = await mockApi(page, {
    ...SHELL,
    "GET /api/jobs/1/sponsorship": { sponsorship: "offered", evidence: "", clearance: "", licensed_sponsor: false, sponsor_name: "", mark: "" },
    "POST /api/jobs/analyze": { sse: [{ type: "job_fit", ranked_jobs: [{ fit_score: 84, level_match: "strong",
      matched_skills: ["Python"], skill_gaps: ["Kubernetes"], reasoning: "Strong backend overlap." }] }] },
    "POST /api/jobs/tailored-cv": { sse: [{ type: "tailored_cv", cv,
      review: { issues: ["Summary didn't name FastAPI"], kept: true } }] },
    "POST /api/documents/preview": { html: "<html><body>CV</body></html>" },
    "POST /api/documents/check": (request) => {
      checked.push(request.postDataJSON());
      return {
        keywords: { matched: ["FastAPI", "Python"], missing_have: ["Docker"], gaps: ["PostgreSQL"], in_ad: 4, score: 67 },
        facts: [{ kind: "number", field: "experience.0.bullets.0", label: "Experience: Intern at Brightwave",
                  value: "35%", message: "“35%” isn't in your persona" }],
        style: [], ats: { pages: 1, checks: [{ check: "Text can be read", ok: true, detail: "212 words" }] },
      };
    },
  });
  await page.goto("/jobs/1");
  await expect(page.getByRole("heading", { name: "Strong fit" })).toBeVisible();
  await page.getByRole("button", { name: "Continue to tailored CV" }).click();

  const checks = page.getByRole("button", { name: /^Checks/ });
  await expect(checks).toContainText("1 thing to check");
  await expect(checks).toContainText("Keywords 2 of 3 you have");
  await expect(checks).toContainText("Reviewed for this ad: 1 fix");
  await checks.click();
  await expect(page.getByText("Summary didn't name FastAPI")).toBeVisible();
  await expect(page.getByText("“35%” isn't in your persona")).toBeVisible();
  await expect(page.getByText("Docker", { exact: true })).toBeVisible();
  expect(checked[0]).toMatchObject({ type: "cv", doc: { name: "Sam Okafor" }, job: { title: job.title } });
  api.expectAllMocked();
});

const answered = (question: string, source: string, answer: string, extra: object = {}) => ({
  question, options: [], kind: "fact", source, answer, because: "", bank_id: "", flags: [], ...extra,
});

test("the review shows where each answer came from and saves the one only you can answer", async ({ page }) => {
  await signIn(page);
  const posted: unknown[] = [];
  const questions = [
    answered("Do you have the right to work in the UK?", "profile", "Yes",
      { options: ["Yes", "No"], because: "Your profile: Right to work / work authorisation in the UK = Yes" }),
    answered("Why do you want to join Company a1?", "drafted", "I want to build your booking services.",
      { kind: "written", flags: ["Paragraph 1: Kafka isn't in your persona"] }),
    answered("Have you ever been convicted of a criminal offence?", "needs_you", "", { options: ["Yes", "No"] }),
  ];
  const api = await mockApi(page, {
    ...SHELL,
    "GET /api/applications": [app("a1", "Pending Review", { questions })],
    "POST /api/answers": (request) => {
      posted.push(request.postDataJSON());
      return { id: "b1", question: "q", answer: "No", kind: "fact", company: "", created_at: "", updated_at: "" };
    },
  });
  await page.goto("/review");
  const panel = page.getByRole("region", { name: "Questions on this form" });
  await expect(panel).toContainText("1 only you can answer");
  await expect(panel).toContainText("1 drafted, check it");
  await expect(panel).toContainText("Your profile: Right to work / work authorisation in the UK = Yes");
  await expect(panel).toContainText("Kafka isn't in your persona");

  // The question nothing answered comes first, with the form's own options.
  await panel.getByLabel("Have you ever been convicted of a criminal offence?").selectOption("No");
  await panel.getByRole("button", { name: "Save answer" }).click();
  await expect.poll(() => posted).toEqual([{ question: "Have you ever been convicted of a criminal offence?",
    answer: "No", kind: "fact", company: "Company a1" }]);
  await expect(panel).toContainText("it fills this in from your saved answers");
  api.expectAllMocked();
});

test("saved answers can be edited and deleted from your persona", async ({ page }) => {
  await signIn(page);
  const saved = { id: "b1", question: "Do you hold a full UK driving licence?", answer: "No", kind: "fact",
                  company: "", created_at: "2026-10-16T10:00:00Z", updated_at: "2026-10-16T10:00:00Z" };
  const puts: unknown[] = [];
  let deleted = false;
  const api = await mockApi(page, {
    ...SHELL,
    "GET /api/answers": [saved],
    "PUT /api/answers/b1": (request) => {
      puts.push(request.postDataJSON());
      return { ...saved, answer: "Yes", updated_at: "2026-10-16T11:00:00Z" };
    },
    "DELETE /api/answers/b1": () => {
      deleted = true;
      return { deleted: "b1" };
    },
  });
  await page.goto("/profile");
  await page.getByRole("button", { name: /^Saved answers/ }).click();
  await expect(page).toHaveURL(/#answers$/);
  await expect(page.getByText("Do you hold a full UK driving licence?")).toBeVisible();

  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Do you hold a full UK driving licence?").fill("Yes");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect.poll(() => puts).toEqual([{ answer: "Yes" }]);
  await expect(page.getByText("Yes", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("button", { name: "Delete it" }).click();
  await expect.poll(() => deleted).toBe(true);
  await expect(page.getByText("Nothing saved yet.", { exact: false })).toBeVisible();
  api.expectAllMocked();
});

test("an answer given in the live review is put on the form by the agent", async ({ page }) => {
  await signIn(page);
  const job = { ...JOBS[0], description: "Python and FastAPI services." };
  await page.addInitScript((j) => sessionStorage.setItem("job_1", JSON.stringify(j)), job);
  // The apply stream stays open for the whole review, which a mocked route can't do: stub it in the page,
  // with window.__pushApply(event) sending the agent's next event.
  await page.addInitScript(() => {
    const realFetch = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (!url.includes("/api/apply")) return realFetch(input, init);
      const encode = (ev: object) => new TextEncoder().encode(`data: ${JSON.stringify(ev)}\n\n`);
      const w = window as unknown as { __pushApply: (ev: object) => void; __applyBody: string };
      w.__applyBody = init?.body instanceof FormData ? Array.from(init.body.keys()).join(",") : "";
      return Promise.resolve(new Response(new ReadableStream({
        start(controller) { w.__pushApply = (ev) => controller.enqueue(encode(ev)); },
      }), { status: 200, headers: { "content-type": "text/event-stream" } }));
    };
  });
  const cv = { name: "Sam Okafor", contact: {}, summary: "Graduate.", skills: [], experience: [], education: [],
               projects: [], certifications: [] };
  const letter = { candidate_name: "Sam Okafor", salutation: "Dear Hiring Manager,", paragraphs: ["I build services."],
                   signoff: "Yours faithfully," };
  const check = { keywords: { matched: [], missing_have: [], gaps: [], in_ad: 0, score: null }, facts: [], style: [], ats: null };
  const inputs: { instruction: string }[] = [];
  const saved: unknown[] = [];
  const api = await mockApi(page, {
    ...SHELL,
    "GET /api/jobs/1/sponsorship": { sponsorship: "offered", evidence: "", clearance: "", licensed_sponsor: false, sponsor_name: "", mark: "" },
    "POST /api/jobs/analyze": { sse: [{ type: "job_fit", ranked_jobs: [{ fit_score: 84, level_match: "strong",
      matched_skills: ["Python"], skill_gaps: [], reasoning: "Strong backend overlap." }] }] },
    "POST /api/jobs/tailored-cv": { sse: [{ type: "tailored_cv", cv }] },
    "POST /api/jobs/cover-letter": { sse: [{ type: "cover_letter", letter }] },
    "POST /api/documents/preview": { html: "<html><body>Doc</body></html>" },
    "POST /api/documents/check": check,
    "POST /api/documents/pdf": { doc_id: "0".repeat(32) },
    "GET /api/browser-stream/sid": { sse: [] },
    "POST /api/answers": (request) => {
      saved.push(request.postDataJSON());
      return { id: "b1", question: "q", answer: "No", kind: "fact", company: "", created_at: "", updated_at: "" };
    },
    "POST /api/browser-input/sid": (request) => {
      inputs.push(request.postDataJSON());
      return { queued: true };
    },
  });
  await page.goto("/jobs/1");
  await page.getByRole("button", { name: "Continue to tailored CV" }).click();
  await page.getByRole("button", { name: /write the cover letter/ }).click();
  await page.getByRole("button", { name: /set up the agent/ }).click();
  await page.getByRole("button", { name: "Start the agent" }).click();

  const blank = { question: "Do you have any unspent criminal convictions?", options: ["Yes", "No"], kind: "fact",
                  source: "needs_you", answer: "", because: "Nothing you've saved says this", bank_id: "", flags: [] };
  await page.waitForFunction(() => "__pushApply" in window);
  expect(await page.evaluate(() => (window as unknown as { __applyBody: string }).__applyBody)).toContain("job_description");
  await page.evaluate((q) => {
    const push = (window as unknown as { __pushApply: (ev: object) => void }).__pushApply;
    push({ type: "start", session_id: "sid", timestamp: 1 });
    push({ type: "browser_blocked", action: "Form filled, but 1 question only you can answer", interactive: true,
           reason: "Answer it", questions: [q], timestamp: 2 });
  }, blank);

  const panel = page.getByRole("region", { name: "Questions on this form" });
  await panel.getByLabel("Do you have any unspent criminal convictions?").selectOption("No");
  await panel.getByRole("button", { name: "Save answer" }).click();
  await expect.poll(() => saved.length).toBe(1);
  await panel.getByRole("button", { name: "Fill it in on the form" }).click();
  await expect.poll(() => inputs.length).toBe(1);
  expect(JSON.parse(inputs[0].instruction)).toEqual({ type: "answers", answers: [
    { question: blank.question, answer: "No", kind: "fact", options: ["Yes", "No"] }] });
  await expect(panel).toContainText("The agent is putting your answer on the form");

  // The agent reports back with the record updated: the prompt to fill it goes away.
  await page.evaluate((q) => {
    const push = (window as unknown as { __pushApply: (ev: object) => void }).__pushApply;
    push({ type: "browser_blocked", action: "Filled in your 1 answer — check them on the page before you submit",
           interactive: true, reason: "", timestamp: 3,
           questions: [{ ...q, source: "saved", answer: "No", because: "Your answer in this review" }] });
  }, blank);
  await expect(panel).toContainText("Your answer in this review");
  await expect(panel.getByRole("button", { name: /Fill it in on the form/ })).toHaveCount(0);
  api.expectAllMocked();
});

test("autopilot: practice runs, the queue, answering a held question and turning on sending", async ({ page }) => {
  await signIn(page);
  const blank = { question: "Do you hold SC clearance?", options: ["Yes", "No"], kind: "fact", source: "needs_you",
                  answer: "", because: "", bank_id: "", flags: [] };
  const run = (id: string, outcome: string, extra: object = {}) => ({
    id, job_id: `job-${id}`, job_title: `Graduate Engineer ${id}`, company: `Company ${id}`, location: "London",
    job_url: `https://boards.greenhouse.io/co/jobs/${id}`, outcome, practice: false, fit_score: 82, reasons: [],
    questions: [], notes: "", cv_doc_id: null, letter_doc_id: null, application_id: null, screenshots: [],
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...extra,
  });
  const runs = [
    run("1", "needs_you", { reasons: ["1 question only you can answer: “Do you hold SC clearance?”"], questions: [blank] }),
    run("2", "ready", { practice: true }),
    run("3", "skipped", { reasons: ["Fit 60 is under your threshold of 75."] }),
  ];
  let settings = { enabled: false, live: false, min_fit: 75, daily_cap: 3 };
  const puts: object[] = [];
  const posts: string[] = [];
  const api = await mockApi(page, {
    ...SHELL,
    "GET /api/autopilot/runs": runs,
    "GET /api/autopilot": () => ({ settings, running: false, step: "", job: "", started_at: null, sent_last_day: 0,
                                   last_run_at: null, next_run_at: null, last: null }),
    "PUT /api/autopilot/settings": (request) => {
      puts.push(request.postDataJSON());
      settings = { ...settings, ...request.postDataJSON() };
      return settings;
    },
    "POST /api/autopilot/run": () => { posts.push("run"); return { status: 202, json: { started: true } }; },
    "POST /api/autopilot/runs/1/retry": () => { posts.push("retry 1"); return { status: 202, json: { started: true } }; },
    "POST /api/answers": { id: "b1", question: blank.question, answer: "No", kind: "fact", company: "", created_at: "",
                           updated_at: "" },
  });
  await page.goto("/autopilot");

  await expect(page.getByText("Practice mode", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /Autopilot/ })).toContainText("1");          // the sidebar badge
  const queue = page.getByRole("tabpanel");
  await expect(queue).toContainText("Graduate Engineer 1");
  await expect(queue).toContainText("only you can answer");

  await queue.getByLabel(blank.question).selectOption("No");
  await queue.getByRole("button", { name: "Save answer" }).click();
  await expect(queue).toContainText("Press Try again");
  await queue.getByRole("button", { name: "Try again with my answers" }).click();
  await expect.poll(() => posts).toEqual(["retry 1"]);

  await page.getByRole("tab", { name: /Practice/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("Would have sent");
  await page.getByRole("tab", { name: /Skipped/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("under your threshold");

  // Sending asks first.
  await page.getByRole("button", { name: "Send applications" }).click();
  await expect(page.getByText("Send applications without asking you?")).toBeVisible();
  expect(puts).toEqual([]);
  await page.getByRole("button", { name: "Turn on sending" }).click();
  await expect.poll(() => puts).toEqual([{ live: true }]);
  await expect(page.getByText("Sending applications", { exact: true })).toBeVisible();

  await page.getByLabel("Most applications sent a day").selectOption("5");
  await expect.poll(() => puts.at(-1)).toEqual({ daily_cap: 5 });

  await page.getByRole("button", { name: "Run now" }).click();
  await expect.poll(() => posts).toEqual(["retry 1", "run"]);
  api.expectAllMocked();
});

test("inbox: setup steps when not configured, then email updates you can confirm, link and undo", async ({ page }) => {
  await signIn(page);
  const status = { configured: false, connected: false, email: null, problem: null, last_sync_at: null, syncing: false,
                   last: null, redirect_uri: "http://localhost/api/gmail/callback" };
  const event = (id: string, decision: string, extra: object = {}) => ({
    id, gmail_id: `g${id}`, received_at: new Date().toISOString(), sender: "Talent <jobs@acme.com>", subject: `Subject ${id}`,
    snippet: "Hi Sam", kind: "interview", company: "Company a1", role: "", summary: `Summary ${id}`, application_id: "a1",
    proposed: "Interview", decision, status_before: "Applied", app_title: "Role a1", app_company: "Company a1",
    app_status: "Applied", ...extra,
  });
  let current: object = status;
  const posts: { path: string; body: unknown }[] = [];
  const record = (path: string) => (request: { postDataJSON: () => unknown }) => {
    posts.push({ path, body: request.postDataJSON() });
    return { id: path };
  };
  const api = await mockApi(page, {
    ...SHELL,
    "GET /api/applications": [app("a1", "Applied"), app("a2", "Applied")],
    "GET /api/gmail": () => current,
    "GET /api/gmail/events": [
      event("1", "suggested"),
      event("2", "unmatched", { application_id: null, app_title: null, app_company: null, app_status: null,
                                kind: "rejected", proposed: "Rejected", company: "Globex" }),
      event("3", "applied", { proposed: "Interview" }),
    ],
    "POST /api/gmail/events/1/confirm": record("confirm 1"),
    "POST /api/gmail/events/2/confirm": record("confirm 2"),
    "POST /api/gmail/events/3/undo": record("undo 3"),
  });
  await page.goto("/inbox");
  await expect(page.getByText("Gmail tracking isn't set up yet")).toBeVisible();
  await expect(page.getByText("http://localhost/api/gmail/callback")).toBeVisible();

  current = { ...status, configured: true, connected: true, email: "sam@gmail.com", last_sync_at: new Date().toISOString() };
  await page.goto("/inbox?gmail=connected");
  await expect(page.getByText("Connected as")).toContainText("sam@gmail.com");
  await expect(page.getByText("Gmail is connected.")).toBeVisible();
  await expect(page.getByRole("link", { name: /Inbox/ })).toContainText("2");       // two wait for you

  const panel = page.getByRole("tabpanel");
  await panel.getByRole("button", { name: "Mark Role a1 as Interview" }).click();
  await expect.poll(() => posts.map((p) => p.path)).toEqual(["confirm 1"]);
  await panel.getByLabel("Which application is this about?").selectOption({ label: "Company a2: Role a2" });
  await panel.getByRole("button", { name: "Link and mark as Rejected" }).click();
  await expect.poll(() => posts.at(-1)).toEqual({ path: "confirm 2", body: { application_id: "a2" } });

  await page.getByRole("tab", { name: /Updated/ }).click();
  await page.getByRole("tabpanel").getByRole("button", { name: "Undo" }).click();
  await expect.poll(() => posts.at(-1)?.path).toBe("undo 3");
  api.expectAllMocked();
});
