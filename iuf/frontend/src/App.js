import { useMemo, useState } from "react";

import {
  ACTIONS_BY_NSF,
  buildHighLevelIntent,
  downloadText,
  validateForm,
} from "./policy";

const initialForm = {
  intentId: "handover-fw-001",
  ueId: "imsi-001010000000001",
  dnn: "oai",
  sst: "1",
  sd: "010203",

  destinationIp: "8.8.8.8/32",
  protocol: "any",
  destinationPort: "",
  direction: "n6-egress",

  nsfType: "firewall",
  action: "drop",
  customAction: "",

  thresholdPps: "10000",
  rateLimitMbps: "10",

  handoverStage: "before-path-switch",
  migrationMode: "make-before-break",

  description:
    "N2 handover 시 Target UPF에 보안 정책 적용",
};

function findLowLevelYaml(response) {
  return (
    response?.result?.lowLevelYaml ||
    response?.lowLevelYaml ||
    ""
  );
}

function App() {
  const [form, setForm] = useState(initialForm);
  const [preview, setPreview] = useState("json");
  const [sending, setSending] = useState(false);
  const [response, setResponse] = useState(null);

  const [
    validationError,
    setValidationError,
  ] = useState("");

  const availableActions =
    ACTIONS_BY_NSF[form.nsfType] || [];

  /*
   * IUF에서는 High-level Intent JSON만 생성한다.
   * Low-level YAML 변환은 Core VM의 app.py가 담당한다.
   */
  const highLevelIntent = useMemo(
    () => buildHighLevelIntent(form),
    [form]
  );

  const highLevelJson = useMemo(
    () =>
      JSON.stringify(
        highLevelIntent,
        null,
        2
      ),
    [highLevelIntent]
  );

  /*
   * NEF를 통해 Core SCF가 반환한 YAML을 찾는다.
   *
   * IUF backend 응답:
   * {
   *   result: {
   *     lowLevelYaml: "..."
   *   }
   * }
   */
  const lowLevelYaml =
    findLowLevelYaml(response);

  function update(event) {
    const { name, value } = event.target;

    setForm((current) => {
      const next = {
        ...current,
        [name]: value,
      };

      /*
       * Firewall/Anti-DDoS 선택이 바뀌면
       * 해당 NSF의 기본 Action을 선택한다.
       */
      if (name === "nsfType") {
        next.action =
          ACTIONS_BY_NSF[value]?.[0]?.value ||
          "custom";

        next.customAction = "";
      }

      /*
       * TCP 또는 UDP가 아니면
       * Destination Port를 사용하지 않는다.
       */
      if (
        name === "protocol" &&
        !["tcp", "udp"].includes(value)
      ) {
        next.destinationPort = "";
      }

      return next;
    });

    setValidationError("");
  }

  async function submit(event) {
    event.preventDefault();

    const error = validateForm(form);

    if (error) {
      setValidationError(error);
      return;
    }

    setSending(true);
    setResponse(null);
    setValidationError("");
    setPreview("json");

    try {
      const result = await fetch(
        "/api/intents",
        {
          method: "POST",

          headers: {
            "Content-Type": "application/json",
          },

          /*
           * High-level Intent만 IUF backend로 보낸다.
           * YAML은 여기에 포함하지 않는다.
           */
          body: JSON.stringify(
            highLevelIntent
          ),
        }
      );

      const body = await result
        .json()
        .catch(() => ({
          error:
            "응답이 JSON 형식이 아닙니다.",
        }));

      const nextResponse = {
        httpStatus: result.status,
        ...body,
      };

      setResponse(nextResponse);

      /*
       * Core SCF가 YAML을 반환했다면
       * 자동으로 YAML 탭을 표시한다.
       */
      if (findLowLevelYaml(nextResponse)) {
        setPreview("yaml");
      }
    } catch (errorObject) {
      setResponse({
        httpStatus: 0,

        error:
          "IUF 서버 연결 실패: " +
          errorObject.message,
      });
    } finally {
      setSending(false);
    }
  }

  const successful =
    response &&
    response.httpStatus >= 200 &&
    response.httpStatus < 300;

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand-mark">
          IUF
        </div>

        <div>
          <p className="eyebrow">
            I2NSF User Function · 5G Handover
          </p>

          <h1>
            Security Intent Console
          </h1>
        </div>

        <div className="route-pill">
          IUF JSON → NEF → Core SCF YAML
        </div>
      </header>

      <div className="layout">
        <section className="card form-card">
          <div className="section-heading">
            <div>
              <span className="step">
                01
              </span>

              <h2>
                High-level Intent 입력
              </h2>
            </div>

            <p>
              UE는 SUPI로 식별하며 실제 UE
              IP는 Core의 SMF 세션에서
              결정합니다.
            </p>
          </div>

          <form onSubmit={submit}>
            <fieldset>
              <legend>
                5G Policy Subject
              </legend>

              <div className="field-grid">
                <label>
                  <span>
                    Intent ID
                  </span>

                  <input
                    name="intentId"
                    value={form.intentId}
                    onChange={update}
                    required
                  />
                </label>

                <label>
                  <span>
                    UE SUPI
                  </span>

                  <input
                    name="ueId"
                    value={form.ueId}
                    onChange={update}
                    required
                  />
                </label>

                <label>
                  <span>
                    DNN
                  </span>

                  <input
                    name="dnn"
                    value={form.dnn}
                    onChange={update}
                    required
                  />
                </label>

                <label>
                  <span>
                    S-NSSAI SST
                  </span>

                  <input
                    name="sst"
                    type="number"
                    min="0"
                    max="255"
                    value={form.sst}
                    onChange={update}
                    required
                  />
                </label>

                <label>
                  <span>
                    S-NSSAI SD
                  </span>

                  <input
                    name="sd"
                    value={form.sd}
                    onChange={update}
                    placeholder="010203"
                    required
                  />
                </label>
              </div>
            </fieldset>

            <fieldset>
              <legend>
                Traffic Selector
              </legend>

              <div className="field-grid">
                <label>
                  <span>
                    Destination IPv4/CIDR
                  </span>

                  <input
                    name="destinationIp"
                    value={
                      form.destinationIp
                    }
                    onChange={update}
                    placeholder="8.8.8.8/32"
                    required
                  />
                </label>

                <label>
                  <span>
                    IP Protocol
                  </span>

                  <select
                    name="protocol"
                    value={form.protocol}
                    onChange={update}
                  >
                    <option value="any">
                      ANY
                    </option>

                    <option value="tcp">
                      TCP
                    </option>

                    <option value="udp">
                      UDP
                    </option>

                    <option value="icmp">
                      ICMP
                    </option>
                  </select>
                </label>

                <label>
                  <span>
                    Destination Port
                  </span>

                  <input
                    name="destinationPort"
                    type="number"
                    min="1"
                    max="65535"
                    value={
                      form.destinationPort
                    }
                    onChange={update}
                    disabled={
                      ![
                        "tcp",
                        "udp",
                      ].includes(
                        form.protocol
                      )
                    }
                    placeholder="예: 443"
                  />
                </label>

                <label>
                  <span>
                    N6 Traffic Direction
                  </span>

                  <select
                    name="direction"
                    value={form.direction}
                    onChange={update}
                  >
                    <option value="n6-egress">
                      N6 Egress (UE → DN)
                    </option>

                    <option value="n6-ingress">
                      N6 Ingress (DN → UE)
                    </option>

                    <option value="bidirectional">
                      Bidirectional
                    </option>
                  </select>
                </label>
              </div>
            </fieldset>

            <fieldset>
              <legend>
                Security Control
              </legend>

              <div className="field-grid">
                <label>
                  <span>
                    Network Security Function
                  </span>

                  <select
                    name="nsfType"
                    value={form.nsfType}
                    onChange={update}
                  >
                    <option value="firewall">
                      Firewall
                    </option>

                    <option value="anti-ddos">
                      Anti-DDoS
                    </option>
                  </select>
                </label>

                <label>
                  <span className="label-with-badge">
                    Enforcement Action

                    <small>
                      변경·확장 가능
                    </small>
                  </span>

                  <select
                    name="action"
                    value={form.action}
                    onChange={update}
                  >
                    {availableActions.map(
                      ({
                        value,
                        label,
                      }) => (
                        <option
                          key={value}
                          value={value}
                        >
                          {label}
                        </option>
                      )
                    )}

                    <option value="custom">
                      Custom action…
                    </option>
                  </select>
                </label>

                {form.action ===
                  "custom" && (
                  <label className="wide-field">
                    <span>
                      Custom Action ID
                    </span>

                    <input
                      name="customAction"
                      value={
                        form.customAction
                      }
                      onChange={update}
                      placeholder="예: mirror-to-sdaf"
                      required
                    />
                  </label>
                )}

                {form.nsfType ===
                  "anti-ddos" && (
                  <label>
                    <span>
                      Detection Threshold
                      (pps)
                    </span>

                    <input
                      name="thresholdPps"
                      type="number"
                      min="1"
                      value={
                        form.thresholdPps
                      }
                      onChange={update}
                      required
                    />
                  </label>
                )}

                {form.action ===
                  "rate-limit" && (
                  <label>
                    <span>
                      Rate Limit (Mbps)
                    </span>

                    <input
                      name="rateLimitMbps"
                      type="number"
                      min="1"
                      value={
                        form.rateLimitMbps
                      }
                      onChange={update}
                      required
                    />
                  </label>
                )}
              </div>

              <p className="field-note">
                목록에 없는 동작은 Custom
                action으로 추가할 수 있습니다.
                Core SCF는 기본 목록 밖의
                Action을 extension으로
                표시합니다.
              </p>
            </fieldset>

            <fieldset>
              <legend>
                Handover Enforcement
              </legend>

              <div className="field-grid">
                <label>
                  <span>
                    Enforcement Stage
                  </span>

                  <select
                    name="handoverStage"
                    value={
                      form.handoverStage
                    }
                    onChange={update}
                  >
                    <option value="before-path-switch">
                      Before Path Switch
                    </option>

                    <option value="after-path-switch">
                      After Path Switch
                    </option>
                  </select>
                </label>

                <label>
                  <span>
                    Policy Migration Mode
                  </span>

                  <select
                    name="migrationMode"
                    value={
                      form.migrationMode
                    }
                    onChange={update}
                  >
                    <option value="make-before-break">
                      Make Before Break
                    </option>

                    <option value="target-only">
                      Target UPF Only
                    </option>

                    <option value="break-before-make">
                      Break Before Make
                    </option>
                  </select>
                </label>

                <label className="wide-field">
                  <span>
                    Description
                  </span>

                  <textarea
                    name="description"
                    value={
                      form.description
                    }
                    rows="3"
                    onChange={update}
                  />
                </label>
              </div>
            </fieldset>

            {validationError && (
              <p className="validation-error">
                {validationError}
              </p>
            )}

            <button
              className="submit-button"
              type="submit"
              disabled={sending}
            >
              {sending
                ? "NEF로 전송 중…"
                : "High-level Intent 전송"}
            </button>
          </form>
        </section>

        <aside className="side-column">
          <section className="card preview-card">
            <div className="section-heading compact">
              <div>
                <span className="step">
                  02
                </span>

                <h2>
                  정책 보기
                </h2>
              </div>

              <div className="preview-tabs">
                <button
                  type="button"
                  className={
                    preview === "json"
                      ? "active"
                      : ""
                  }
                  onClick={() =>
                    setPreview("json")
                  }
                >
                  IUF JSON
                </button>

                <button
                  type="button"
                  className={
                    preview === "yaml"
                      ? "active"
                      : ""
                  }
                  onClick={() =>
                    setPreview("yaml")
                  }
                  disabled={!lowLevelYaml}
                >
                  Core YAML
                </button>
              </div>
            </div>

            <p className="preview-kind">
              {preview === "json"
                ? "IUF에서 생성한 High-level Intent"
                : "Core SCF가 변환한 Low-level Policy"}
            </p>

            <pre>
              {preview === "json"
                ? highLevelJson
                : lowLevelYaml ||
                  "전송이 성공하면 Core SCF의 YAML이 표시됩니다."}
            </pre>

            <div className="download-row">
              <button
                type="button"
                onClick={() =>
                  downloadText(
                    `${
                      form.intentId ||
                      "intent"
                    }.json`,

                    highLevelJson,

                    "application/json"
                  )
                }
              >
                JSON 저장
              </button>

              <button
                type="button"
                disabled={!lowLevelYaml}
                onClick={() =>
                  downloadText(
                    `${
                      form.intentId ||
                      "policy"
                    }.yaml`,

                    lowLevelYaml,

                    "application/yaml"
                  )
                }
              >
                YAML 저장
              </button>
            </div>
          </section>

          <section
            className={
              `card result-card ` +
              (
                response
                  ? successful
                    ? "success"
                    : "failure"
                  : "idle"
              )
            }
          >
            <div className="section-heading compact">
              <div>
                <span className="step">
                  03
                </span>

                <h2>
                  전송 결과
                </h2>
              </div>

              {response && (
                <span className="status-code">
                  HTTP{" "}
                  {response.httpStatus ||
                    "ERR"}
                </span>
              )}
            </div>

            {!response && (
              <p className="empty-result">
                NEF와 Core SCF의 처리 결과가
                여기에 표시됩니다.
              </p>
            )}

            {response && (
              <>
                {response.requestId && (
                  <div className="request-id">
                    <span>
                      Request ID
                    </span>

                    <code>
                      {response.requestId}
                    </code>
                  </div>
                )}

                <pre>
                  {JSON.stringify(
                    response,
                    null,
                    2
                  )}
                </pre>
              </>
            )}
          </section>
        </aside>
      </div>
    </main>
  );
}

export default App;
