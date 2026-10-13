// The receipt is created only after the collector's authenticated freshness and
// attachment checks pass. It contains no school data or credentials.
export const VERIFIED_STEP = 'Verify fresh published report';
export const RECEIPT_PREFIX = 'mahbrus-verified-publication-v1-';
type VerificationData = {
  jobs?: { steps?: { name: string; conclusion: string }[] }[];
  artifacts?: { name: string; expired: boolean; size_in_bytes: number }[];
};
export async function publicationVerified(github: (path: string) => Promise<VerificationData>, run: { id: number; run_attempt?: number }) {
  const result = await github(`/runs/${run.id}/jobs?per_page=100&filter=latest`);
  const steps = (Array.isArray(result.jobs) ? result.jobs : []).flatMap(job => job.steps || []);
  const verification = steps.find(step => step.name === VERIFIED_STEP);
  if (verification) return verification.conclusion === 'success';
  // GitHub can omit steps even for a completed job. An artifact from this
  // exact run attempt provides independent proof; a green run alone does not.
  const attempt = run.run_attempt ?? 1;
  if (!Number.isSafeInteger(attempt) || attempt < 1) return false;
  const receipt = await github(`/runs/${run.id}/artifacts?per_page=100`);
  return Array.isArray(receipt.artifacts) && receipt.artifacts.some(artifact =>
    artifact.name === RECEIPT_PREFIX + attempt && artifact.expired === false &&
    Number.isSafeInteger(artifact.size_in_bytes) && artifact.size_in_bytes > 0 && artifact.size_in_bytes <= 4096);
}
