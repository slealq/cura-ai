'use client';

import MarketingShell from '@/components/marketing/MarketingShell';

const LAST_UPDATED = 'July 9, 2026';

export default function TermsPage() {
  return (
    <MarketingShell>
      <article className="mx-auto max-w-3xl px-6 py-16">
        <h1 className="text-3xl font-bold tracking-tight">Terms of Service</h1>
        <p className="mt-2 text-sm text-muted-foreground">Last updated: {LAST_UPDATED}</p>

        <div className="mt-8 space-y-8 text-sm leading-relaxed text-muted-foreground [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-foreground">
          <section>
            <h2>1. About SightLab</h2>
            <p className="mt-2">
              SightLab (&quot;the Service&quot;) is an AI image platform that lets you upload, organize,
              search, and analyze images, train custom AI style models, and generate or edit images
              using third-party AI models. By creating an account or using the Service you agree to
              these Terms.
            </p>
          </section>

          <section>
            <h2>2. Your account</h2>
            <p className="mt-2">
              You must provide accurate information when registering and keep your credentials
              secure. You are responsible for all activity under your account. You must be at least
              18 years old to use the Service.
            </p>
          </section>

          <section>
            <h2>3. Your content</h2>
            <p className="mt-2">
              You retain all rights to images you upload and to images generated from your prompts
              and models, to the extent permitted by applicable law and the licenses of the
              underlying AI models. You grant SightLab a limited license to store, process, and
              display your content solely to operate the Service. You are responsible for ensuring
              you have the rights to any content you upload, and that your use of the Service does
              not violate the rights of others.
            </p>
          </section>

          <section>
            <h2>4. Acceptable use</h2>
            <p className="mt-2">You agree not to use the Service to create, upload, or distribute content that:</p>
            <ul className="mt-2 list-disc pl-6 space-y-1">
              <li>is illegal, or infringes intellectual-property or privacy rights;</li>
              <li>depicts real people in a misleading or harmful way, including non-consensual imagery;</li>
              <li>constitutes child sexual abuse material of any kind;</li>
              <li>is intended to harass, defame, or deceive.</li>
            </ul>
            <p className="mt-2">We may suspend or terminate accounts that violate these rules.</p>
          </section>

          <section>
            <h2>5. Sparks, payments, and refunds</h2>
            <p className="mt-2">
              Paid features are metered in <strong>sparks</strong>, a prepaid credit. Sparks are
              purchased as one-time packs or granted monthly through subscriptions. Payments are
              processed by our merchant of record, Lemon Squeezy, LLC, whose own terms apply to the
              payment transaction. Prices are shown at checkout.
            </p>
            <ul className="mt-2 list-disc pl-6 space-y-1">
              <li>Pack sparks do not expire. Subscription sparks refresh each billing period.</li>
              <li>Subscriptions renew automatically and can be cancelled anytime, effective at the end of the current period.</li>
              <li>
                Refunds: unused pack purchases are refundable within 14 days. Once sparks from a
                purchase have been spent, that purchase is refundable only at our discretion,
                prorated to the unused balance.
              </li>
            </ul>
          </section>

          <section>
            <h2>6. AI output disclaimer</h2>
            <p className="mt-2">
              AI-generated tags, descriptions, and images are produced by machine-learning models
              and may be inaccurate, biased, or unsuitable for your purpose. The Service is provided
              &quot;as is&quot; without warranties of any kind. You are responsible for reviewing
              output before relying on or publishing it.
            </p>
          </section>

          <section>
            <h2>7. Limitation of liability</h2>
            <p className="mt-2">
              To the maximum extent permitted by law, SightLab&apos;s total liability for any claim
              arising from the Service is limited to the amount you paid us in the twelve months
              preceding the claim. We are not liable for indirect, incidental, or consequential
              damages.
            </p>
          </section>

          <section>
            <h2>8. Termination</h2>
            <p className="mt-2">
              You may delete your account at any time. We may suspend or terminate the Service or
              your account for violation of these Terms, with notice where practicable. Upon
              termination your content will be deleted in accordance with our Privacy Policy.
            </p>
          </section>

          <section>
            <h2>9. Changes</h2>
            <p className="mt-2">
              We may update these Terms as the Service evolves. Material changes will be announced
              in-app or by email. Continued use after changes take effect constitutes acceptance.
            </p>
          </section>

          <section>
            <h2>10. Contact</h2>
            <p className="mt-2">
              Questions about these Terms:{' '}
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
