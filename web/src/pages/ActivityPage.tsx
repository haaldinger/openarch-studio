import { useEffect, useState } from "react";
import { PageIntro } from "../components/PageIntro";
import { EnrichmentStatus } from "../components/EnrichmentStatus";
import { listJobs, retryJob } from "../api";
import { useSession } from "../session";
import type { Job } from "../types";

export function ActivityPage() {
  const { generation } = useSession();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const poll = () =>
      listJobs()
        .then((res) => active && setJobs(res.jobs))
        .catch(() => active && setError("Could not load jobs."));
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [generation]);

  return (
    <>
      <PageIntro
        eyebrow="Studio pipeline"
        title="Activity"
        lede="Enrichment jobs and their stages. The original document stays safe in OpenArch even when a stage fails — retry picks up from the start."
      />
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {jobs.length === 0 ? (
        <div className="placeholder-panel">
          <p className="placeholder-title">No jobs yet</p>
          <p className="muted">
            Upload a document in the Library to watch it move through extraction, chunking, and
            embedding.
          </p>
        </div>
      ) : (
        <div className="job-list">
          {jobs.map((job) => (
            <div key={job.id} className="job-card">
              <div className="job-head">
                <span className="job-name">{job.filename}</span>
                <span className={`job-state job-${job.state}`}>{job.state}</span>
              </div>
              <EnrichmentStatus stages={job.stages} />
              {(job.state === "failed" || job.stages.some((s) => s.status === "failed")) && (
                <div className="job-foot">
                  {job.error && <span className="job-error">{job.error}</span>}
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() => retryJob(job.id).catch(() => undefined)}
                  >
                    Retry
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
