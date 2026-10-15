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

test("a signed-out visitor is sent to the login page", async ({ page }) => {
  const api = await mockApi(page, {});
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Welcome Back" })).toBeVisible();
  api.expectAllMocked();
});

test("logging in keeps the token and opens the dashboard", async ({ page }) => {
  let form = "";
  const api = await mockApi(page, {
    "POST /api/login": (request) => {
      form = request.postData() ?? "";
      return { access_token: "fresh-token", token_type: "bearer" };
    },
    "GET /api/onboarding/status": { complete: true },
    "GET /api/applications": [],
    "POST /api/score-skills": { skill_risks: [] },
  });
  await page.goto("/login");
  await page.locator('input[type="email"]').fill("sam@example.com");
  await page.locator('input[type="password"]').fill("correct horse");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  expect(form).toContain("sam@example.com");
  expect(await page.evaluate(() => localStorage.getItem("windrush_token"))).toBe("fresh-token");
  api.expectAllMocked();
});

test("a wrong password shows the server's message", async ({ page }) => {
  const api = await mockApi(page, {
    "POST /api/login": { status: 401, json: { detail: "Incorrect email or password" } },
  });
  await page.goto("/login");
  await page.locator('input[type="email"]').fill("sam@example.com");
  await page.locator('input[type="password"]').fill("wrong");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByText("Incorrect email or password")).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
  api.expectAllMocked();
});

test("the feed shows each job's badges and sends the filters to the API", async ({ page }) => {
  await signIn(page);
  const api = await mockApi(page, {
    // The server picks "possible" for a profile that needs sponsorship and says so.
    "GET /api/jobs": { jobs: JOBS, has_more: false, discovering: false, sponsorship: "possible" },
  });
  await page.goto("/jobs");

  // A card: the innermost element holding both its title and its location.
  const card = (job: (typeof JOBS)[number]) => page.locator("div")
    .filter({ has: page.getByRole("heading", { name: job.title, exact: true }) })
    .filter({ hasText: job.location }).last();
  await expect(page.getByText("2 jobs")).toBeVisible();
  for (const text of ["Visa sponsorship", "No experience needed", "Degree required"]) {
    await expect(card(JOBS[0]).getByText(text, { exact: true })).toBeVisible();
  }
  for (const text of ["Licensed sponsor", "SC clearance", "2+ yrs exp"]) {
    await expect(card(JOBS[1]).getByText(text, { exact: true })).toBeVisible();
  }
  await expect(card(JOBS[1]).getByText("Degree required")).toHaveCount(0);   // only preferred

  const sponsorship = page.locator('select[title^="Possible hides"]');
  const experience = page.locator('select[title^="Hides jobs whose ad asks"]');
  await expect(sponsorship).toHaveValue("possible");

  await experience.selectOption({ label: "No experience required" });
  await expect.poll(() => api.params("/api/jobs").at(-1)?.get("max_years")).toBe("0");

  await page.getByRole("button", { name: "🎓 No degree needed" }).click();
  await expect.poll(() => api.params("/api/jobs").at(-1)?.get("no_degree")).toBe("true");
  expect(api.params("/api/jobs").at(-1)?.get("max_years")).toBe("0");      // filters combine

  await page.getByRole("button", { name: "✕ Clear filters" }).click();
  await expect.poll(() => api.params("/api/jobs").at(-1)?.has("no_degree")).toBe(false);
  const last = api.params("/api/jobs").at(-1)!;
  expect([last.has("max_years"), last.has("sponsorship"), last.get("page")]).toEqual([false, false, "1"]);
  api.expectAllMocked();
});

test("an expired session sends you back to the login page", async ({ page }) => {
  const api = await mockApi(page, {
    "GET /api/jobs": { status: 401, json: { detail: "Could not validate credentials" } },
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
    "GET /api/persona": PERSONA,
    "PUT /api/persona": (request) => {
      saved = request.postDataJSON();
      return { status: "ok" };
    },
  });
  await page.goto("/profile");
  await page.getByRole("button", { name: "Preferences", exact: true }).click();

  // Typed key by key: a comma or a space must survive until the next word is typed.
  await page.getByPlaceholder("e.g. Graduate Software Engineer, Junior ML Engineer")
    .pressSequentially("Graduate Software Engineer, Junior ML Engineer");
  await page.getByPlaceholder("e.g. London, Manchester, New York").pressSequentially("London, New York");
  await page.getByRole("button", { name: "Save Persona" }).click();

  await expect.poll(() => saved).not.toBeNull();
  expect(saved!.preferences.target_titles).toEqual(["Graduate Software Engineer", "Junior ML Engineer"]);
  expect(saved!.preferences.preferred_locations).toEqual(["London", "New York"]);
  expect(saved!.core_info.first_name).toBe("Sam");                       // the rest of the profile is kept
  api.expectAllMocked();
});
