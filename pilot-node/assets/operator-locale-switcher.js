(() => {
  const payloadNode = document.getElementById("operator-locale-payload");
  const switcher = document.getElementById("locale-switcher");
  if (!payloadNode || !switcher) {
    return;
  }

  let payload = {};
  try {
    payload = JSON.parse(payloadNode.textContent || "{}");
  } catch (_error) {
    return;
  }

  const current = String(payload.current || "da");
  const nodeDefault = String(payload.node_default || payload.default || "da");
  const choices = Array.isArray(payload.choices) ? payload.choices : [];
  const defaultChoice = choices.find((choice) => choice.id === nodeDefault);
  const defaultLabel = payload.default_option_label || "Node default";

  switcher.innerHTML = "";

  const nodeOption = document.createElement("option");
  nodeOption.value = "default";
  nodeOption.textContent = defaultChoice
    ? `${defaultLabel}: ${defaultChoice.native_label || defaultChoice.label || nodeDefault}`
    : `${defaultLabel}: ${nodeDefault}`;
  switcher.appendChild(nodeOption);

  for (const choice of choices) {
    const option = document.createElement("option");
    option.value = choice.id;
    option.textContent = choice.native_label || choice.label || choice.id;
    switcher.appendChild(option);
  }

  switcher.value = current === nodeDefault ? "default" : current;

  switcher.addEventListener("change", () => {
    const url = new URL(window.location.href);
    if (switcher.value === "default") {
      url.searchParams.set("lang", "default");
    } else {
      url.searchParams.set("lang", switcher.value);
    }
    window.location.assign(url.toString());
  });
})();
