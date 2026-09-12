import { useMemo, useState } from "react";

const initialForm = {
  intentId: "intent-001",
  ueId: "imsi-001010000000001",
  ueIp: "10.0.1.1",
  dnn: "oai",
  appId: "edge-demo",
  targetDnai: "edge-b",
  action: "record-only",
  description: "IUF to NEF to Flask SCF receipt test",
};

const fields = [
  ["intentId", "Intent ID", "intent-001", true],
  ["ueId", "UE ID", "imsi-001010000000001", true],
  ["ueIp", "UE IPv4", "10.0.1.1", true],
  ["dnn", "DNN", "oai", true],
  ["appId", "Application ID", "edge-demo", true],
  ["targetDnai", "Target DNAI", "edge-b", true],
];

function App() {
  const [form, setForm] = useState(initialForm);
  const [sending, setSending] = useState(false);
  const [response, setResponse] = useState(null);

  const intent = useMemo(
    () => ({
      intentId: form.intentId.trim(),
      ueId: form.ueId.trim(),
      ueIp: form.ueIp.trim(),
      dnn: form.dnn.trim(),
      appId: form.appId.trim(),
      targetDnai: form.targetDnai.trim(),
      policy: {
        action: form.action,
        description: form.description.trim(),
      },
    }),
    [form],
  );

  function update(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    setSending(true);
    setResponse(null);

    try {
      const result = await fetch("/api/intents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(intent),
      });
      const body = await result.json().catch(() => ({ error: "응답이 JSON 형식이 아닙니다." }));
      setResponse({ httpStatus: result.status, ...body });
    } catch (error) {
      setResponse({ httpStatus: 0, error: `IUF 서버 연결 실패: ${error.message}` });
    } finally {
      setSending(false);
    }
  }

  const successful = response && response.httpStatus >= 200 && response.httpStatus < 300;

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand-mark">IUF</div>
        <div>
          <p className="eyebrow">I2NSF User Function</p>
          <h1>Security Intent Console</h1>
        </div>
        <div className="route-pill">IUF → NEF → Flask SCF</div>
      </header>

      <div className="layout">
        <section className="card form-card">
          <div className="section-heading">
            <div>
              <span className="step">01</span>
              <h2>Intent 입력</h2>
            </div>
            <p>UE와 대상 경로에 적용할 실험용 보안 의도를 입력합니다.</p>
          </div>

          <form onSubmit={submit}>
            <div className="field-grid">
              {fields.map(([name, label, placeholder, required]) => (
                <label key={name}>
                  <span>{label}</span>
                  <input
                    name={name}
                    value={form[name]}
                    placeholder={placeholder}
                    required={required}
                    onChange={update}
                    autoComplete="off"
                  />
                </label>
              ))}

              <label>
                <span>Policy Action</span>
                <select name="action" value={form.action} onChange={update}>
                  <option value="record-only">record-only</option>
                  <option value="drop">drop</option>
                  <option value="pass">pass</option>
                  <option value="rate-limit">rate-limit</option>
                </select>
              </label>

              <label className="wide-field">
                <span>Description</span>
                <textarea
                  name="description"
                  value={form.description}
                  rows="3"
                  onChange={update}
                />
              </label>
            </div>

            <button className="submit-button" type="submit" disabled={sending}>
              {sending ? "NEF로 전송 중…" : "Intent 전송"}
            </button>
          </form>
        </section>

        <aside className="side-column">
          <section className="card preview-card">
            <div className="section-heading compact">
              <div>
                <span className="step">02</span>
                <h2>JSON 미리보기</h2>
              </div>
            </div>
            <pre>{JSON.stringify(intent, null, 2)}</pre>
          </section>

          <section className={`card result-card ${response ? (successful ? "success" : "failure") : "idle"}`}>
            <div className="section-heading compact">
              <div>
                <span className="step">03</span>
                <h2>전송 결과</h2>
              </div>
              {response && <span className="status-code">HTTP {response.httpStatus || "ERR"}</span>}
            </div>

            {!response && <p className="empty-result">전송 후 NEF 응답과 requestId가 표시됩니다.</p>}
            {response && (
              <>
                {response.requestId && (
                  <div className="request-id">
                    <span>Request ID</span>
                    <code>{response.requestId}</code>
                  </div>
                )}
                <pre>{JSON.stringify(response, null, 2)}</pre>
              </>
            )}
          </section>
        </aside>
      </div>
    </main>
  );
}

export default App;


