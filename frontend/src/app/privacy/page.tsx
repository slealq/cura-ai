'use client';

import MarketingShell from '@/components/marketing/MarketingShell';

const LAST_UPDATED = 'July 9, 2026';

export default function PrivacyPage() {
  return (
    <MarketingShell>
      <article className="mx-auto max-w-3xl px-6 py-16">
        <h1 className="text-3xl font-bold tracking-tight">Privacy Policy</h1>
        <p className="mt-2 text-sm text-muted-foreground">Last updated: {LAST_UPDATED}</p>

        <div className="mt-8 space-y-8 text-sm leading-relaxed text-muted-foreground [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-foreground">
          <section>
            <h2>1. What we collect</h2>
            <ul className="mt-2 list-disc pl-6 space-y-1">
              <li><strong>Account data</strong> — email address, display name, and password hash (or Google account identifier if you sign in with Google).</li>
              <li><strong>Content</strong> — images you upload, models you train, prompts you write, and images you generate or edit.</li>
              <li><strong>Usage data</strong> — operations you run, credits spent, and technical logs (request identifiers, timestamps, errors) used to operate and debug the Service.</li>
              <li><strong>Payment data</strong> — handled by our merchant of record, Lemon Squeezy. We never see or store your card details; we receive only order metadata (amount, product, status).</li>
            </ul>
          </section>

          <section>
            <h2>2. How we use it</h2>
            <p className="mt-2">
              We use your data solely to provide the Service: storing and processing your images,
              running the AI operations you request, metering usage, processing payments, and
              keeping the Service reliable and secure. We do not sell your data or use your content
              to train our own or third-party foundation models.
            </p>
          </section>

          <section>
            <h2>3. AI processing subprocessors</h2>
            <p className="mt-2">
              When you run AI operations, the relevant content (an image, a prompt) is sent to the
              model provider needed for that operation. Depending on your chosen models these may
              include OpenAI, Anthropic, fal.ai, and xAI (via OpenRouter). Their processing is
              governed by their respective API data-usage policies, which do not permit training on
              API data by default.
            </p>
          </section>

          <section>
            <h2>4. Infrastructure &amp; other processors</h2>
            <ul className="mt-2 list-disc pl-6 space-y-1">
              <li><strong>Microsoft Azure</strong> — hosting, database, and file storage.</li>
              <li><strong>Lemon Squeezy</strong> — payment processing and receipts.</li>
              <li><strong>Sentry</strong> — error and performance monitoring (technical events, not your images).</li>
            </ul>
          </section>

          <section>
            <h2>5. Data isolation &amp; security</h2>
            <p className="mt-2">
              Your images, models, and results are isolated to your account and are not visible to
              other users. Data is encrypted in transit (TLS) and at rest by our cloud provider.
              API keys you store with us are encrypted at the application level.
            </p>
          </section>

          <section>
            <h2>6. Retention &amp; deletion</h2>
            <p className="mt-2">
              Your content is retained while your account is active. If you delete content, it is
              removed from active storage; if you delete your account, all associated content and
              personal data are deleted, except records we must keep for tax, accounting, or fraud
              prevention (kept in minimized form). To request deletion, contact us at the address
              below.
            </p>
          </section>

          <section>
            <h2>7. Cookies &amp; local storage</h2>
            <p className="mt-2">
              We use browser local storage for authentication tokens and preferences (like theme).
              We do not use advertising or cross-site tracking cookies.
            </p>
          </section>

          <section>
            <h2>8. Your rights</h2>
            <p className="mt-2">
              You may access, correct, export, or delete your personal data at any time — most of
              this is available directly in the app, and we will handle the rest by email. If you
              are in a jurisdiction with specific data-protection rights (e.g., GDPR), we honor
              those requests.
            </p>
          </section>

          <section>
            <h2>9. Changes</h2>
            <p className="mt-2">
              We may update this policy as the Service evolves. Material changes will be announced
              in-app or by email.
            </p>
          </section>

          <section>
            <h2>10. Contact</h2>
            <p className="mt-2">
              Privacy questions or requests:{' '}
              <a href="mailto:stuart.leal23@gmail.com" className="underline hover:text-foreground">
                stuart.leal23@gmail.com
              </a>
            </p>
          </section>
        </div>
      </article>
    </MarketingShell>
  );
}
