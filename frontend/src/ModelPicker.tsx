import { selectProvider } from "./modelSettings";
import type { ModelConfig, WorkspaceSettings } from "./types";
export function ModelPicker({
  settings,
  value,
  onChange,
  disabled = false,
}: {
  settings: WorkspaceSettings;
  value: ModelConfig;
  onChange: (value: ModelConfig) => void;
  disabled?: boolean;
}) {
  const provider = settings.providers.find(
    (item) => item.id === value.provider,
  );
  const efforts = provider?.reasoning_efforts.length
    ? provider.reasoning_efforts
    : [value.reasoning_effort];
  return (
    <div className="model-picker">
      <label>
        Provider
        <select
          value={value.provider}
          disabled={disabled}
          onChange={(event) =>
            onChange(selectProvider(settings, event.target.value, value))
          }
        >
          {settings.providers.map((item) => (
            <option key={item.id} value={item.id} disabled={!item.configured}>
              {item.label}
              {item.configured ? "" : " · Not configured"}
            </option>
          ))}
        </select>
      </label>
      <div className="model-picker-fields">
        <label>
          Model
          <input
            required
            disabled={disabled || !provider?.configured}
            value={value.model}
            onChange={(event) =>
              onChange({ ...value, model: event.target.value })
            }
            placeholder={provider?.default_model ?? "Model name"}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label>
          Reasoning
          <select
            disabled={disabled || !provider?.configured}
            value={value.reasoning_effort}
            onChange={(event) =>
              onChange({ ...value, reasoning_effort: event.target.value })
            }
          >
            {efforts.map((effort) => (
              <option key={effort} value={effort}>
                {effort}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="model-picker-note">
        Model must support tool calling; reasoning options depend on the model.
        Credentials stay on the server. Only configured providers can be
        selected.
      </p>
    </div>
  );
}
