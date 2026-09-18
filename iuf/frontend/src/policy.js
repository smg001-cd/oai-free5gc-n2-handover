export const ACTIONS_BY_NSF = {
  firewall: [
    { value: "drop", label: "Drop" },
    { value: "reject", label: "Reject" },
    { value: "accept", label: "Accept" },
    { value: "log", label: "Log only" },
  ],

  "anti-ddos": [
    {
      value: "rate-limit",
      label: "Rate limit",
    },
    {
      value: "drop",
      label: "Drop",
    },
    {
      value: "alert",
      label: "Alert",
    },
    {
      value: "redirect-scrubber",
      label: "Redirect to scrubber",
    },
  ],
};

function optionalNumber(value) {
  if (
    value === "" ||
    value === null ||
    value === undefined
  ) {
    return undefined;
  }

  return Number(value);
}

export function buildHighLevelIntent(form) {
  const action =
    form.action === "custom"
      ? form.customAction.trim()
      : form.action;

  const traffic = {
    destinationIpv4Cidr:
      form.destinationIp.trim(),

    protocol:
      form.protocol,

    direction:
      form.direction,
  };

  const destinationPort =
    optionalNumber(
      form.destinationPort
    );

  if (destinationPort !== undefined) {
    traffic.destinationPort =
      destinationPort;
  }

  const parameters = {};

  if (form.nsfType === "anti-ddos") {
    parameters.detectionThresholdPps =
      optionalNumber(
        form.thresholdPps
      );
  }

  if (action === "rate-limit") {
    parameters.rateLimitMbps =
      optionalNumber(
        form.rateLimitMbps
      );
  }

  return {
    schemaVersion:
      "i2nsf.intent/v1alpha1",

    intentId:
      form.intentId.trim(),

    subject: {
      supi:
        form.ueId.trim(),

      dnn:
        form.dnn.trim(),

      snssai: {
        sst:
          Number(form.sst),

        sd:
          form.sd
            .trim()
            .toUpperCase(),
      },
    },

    trigger: {
      type:
        "n2-handover",

      enforcementStage:
        form.handoverStage,
    },

    traffic,

    securityControl: {
      nsfType:
        form.nsfType,

      action,

      parameters,
    },

    policyMigration: {
      mode:
        form.migrationMode,

      sourceRemoval:
        "after-target-active",
    },

    description:
      form.description.trim(),
  };
}

function isIpv4OrCidr(value) {
  const parts =
    value.split("/");

  if (parts.length > 2) {
    return false;
  }

  const octets =
    parts[0].split(".");

  if (
    octets.length !== 4 ||
    octets.some(
      (octet) =>
        !/^\d{1,3}$/.test(octet) ||
        Number(octet) > 255
    )
  ) {
    return false;
  }

  if (
    parts.length === 2 &&
    (
      !/^\d{1,2}$/.test(parts[1]) ||
      Number(parts[1]) > 32
    )
  ) {
    return false;
  }

  return true;
}

export function validateForm(form) {
  if (
    !/^[A-Za-z0-9_.:-]{1,128}$/.test(
      form.intentId.trim()
    )
  ) {
    return (
      "Intent ID는 영문, 숫자, 점, " +
      "밑줄, 콜론, 하이픈만 사용할 수 있습니다."
    );
  }

  if (!form.ueId.trim()) {
    return "UE SUPI를 입력해야 합니다.";
  }

  if (!form.dnn.trim()) {
    return "DNN을 입력해야 합니다.";
  }

  const sst =
    Number(form.sst);

  if (
    !Number.isInteger(sst) ||
    sst < 0 ||
    sst > 255
  ) {
    return (
      "S-NSSAI SST는 " +
      "0~255의 정수여야 합니다."
    );
  }

  if (
    !/^[0-9A-Fa-f]{6}$/.test(
      form.sd.trim()
    )
  ) {
    return (
      "S-NSSAI SD는 " +
      "6자리 16진수여야 합니다."
    );
  }

  if (
    !isIpv4OrCidr(
      form.destinationIp.trim()
    )
  ) {
    return (
      "Destination은 IPv4 또는 " +
      "IPv4/CIDR 형식이어야 합니다. " +
      "예: 8.8.8.8/32"
    );
  }

  if (
    ["tcp", "udp"].includes(
      form.protocol
    ) &&
    form.destinationPort
  ) {
    const port =
      Number(form.destinationPort);

    if (
      !Number.isInteger(port) ||
      port < 1 ||
      port > 65535
    ) {
      return (
        "Destination Port는 " +
        "1~65535의 정수여야 합니다."
      );
    }
  }

  if (
    form.action === "custom" &&
    !/^[A-Za-z0-9_.:-]{1,64}$/.test(
      form.customAction.trim()
    )
  ) {
    return (
      "Custom Action ID는 영문, 숫자, " +
      "점, 밑줄, 콜론, 하이픈만 사용할 수 있습니다."
    );
  }

  if (
    form.nsfType === "anti-ddos" &&
    Number(form.thresholdPps) < 1
  ) {
    return (
      "Anti-DDoS 탐지 임계값은 " +
      "1 pps 이상이어야 합니다."
    );
  }

  if (
    form.action === "rate-limit" &&
    Number(form.rateLimitMbps) < 1
  ) {
    return (
      "Rate Limit 값은 " +
      "1 Mbps 이상이어야 합니다."
    );
  }

  return "";
}

export function downloadText(
  filename,
  contents,
  mimeType
) {
  const blob =
    new Blob(
      [contents],
      {
        type:
          `${mimeType};charset=utf-8`,
      }
    );

  const url =
    URL.createObjectURL(blob);

  const anchor =
    document.createElement("a");

  anchor.href = url;
  anchor.download = filename;

  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();

  URL.revokeObjectURL(url);
}
