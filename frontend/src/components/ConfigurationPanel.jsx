/**
 * The Figma "Configuration" sidebar: what to check, and against what.
 *
 * Three of the design's controls survive; two do not, and the difference is
 * whether the backend has the data behind them.
 *
 * - **Product category** is a text field, not the design's dropdown. It selects
 *   which rules apply, and the categories live in `ProductCategory` rows - but
 *   no endpoint lists them (`GET /api/v1/products/` is documented as planned).
 *   A dropdown would mean hardcoding backend rows into JavaScript, which drifts
 *   silently the moment a category is added or deactivated. The backend
 *   validates the code and rejects an unknown one with a message this screen
 *   renders, so a typo is caught where the answer actually is.
 * - **Jurisdiction & ruleset** is read-only. There is one ruleset and the
 *   client cannot choose it - and it must not be able to. Applicability is
 *   answered by the engine from the loaded rule set and the commodity's
 *   category; a verdict a client could steer by picking its own rules would be
 *   worth nothing. What is shown instead is what is actually loaded, read from
 *   `/health/`.
 * - **Inspection scope** is gone. The design's "Mandatory Declarations Only"
 *   has no counterpart in the API - the request body has no scope, rule,
 *   check-type or severity parameter, deliberately. The panel slot is used for
 *   the view type instead, which is a real `ProductImage.ViewType` the API
 *   accepts and which genuinely changes how a result should be read.
 *
 * The design's "Findings Requirements Preview" - a list of Product Name, Net
 * Quantity, MRP and so on - is deliberately not reproduced. Those are legal
 * requirements. Listing them in JSX would be hardcoding the law into the
 * browser, and it would go stale against the loaded rules without anything
 * failing. What was actually required is shown after evaluation, in each
 * finding's own `requirement`, in the rule's own words.
 */

const VIEW_TYPES = [
  ['unspecified', 'Not specified'],
  ['front', 'Front panel'],
  ['back', 'Back panel'],
  ['principal_display', 'Principal display panel'],
  ['label', 'Label close-up'],
  ['other', 'Other'],
];

export function ConfigurationPanel({
  categoryCode,
  onCategoryCodeChange,
  viewType,
  onViewTypeChange,
  health,
  canSubmit,
  isBusy,
  busyLabel,
  onReset,
}) {
  return (
    <div className="card">
      <div className="card__header">
        <h2 className="card__title">Configuration</h2>
      </div>

      <div className="card__body">
        <div className="field">
          <label htmlFor="scan-category">Product category</label>
          <input
            id="scan-category"
            type="text"
            value={categoryCode}
            placeholder="e.g. packaged-food"
            disabled={isBusy}
            onChange={(event) => onCategoryCodeChange(event.target.value)}
          />
          <p className="hint">
            Determines which rules apply. Leave blank if unknown — the result
            will say the category was not known rather than assume one.
          </p>
        </div>

        <div className="field">
          <label htmlFor="scan-view-type">Which panel is this?</label>
          <select
            id="scan-view-type"
            value={viewType}
            disabled={isBusy}
            onChange={(event) => onViewTypeChange(event.target.value)}
          >
            {VIEW_TYPES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <p className="hint">
            An absent declaration on a photograph of the front panel is not
            evidence the package lacks one.
          </p>
        </div>

        <div className="field">
          {/*
            Not a <label>: there is no control to label. This value is not
            selectable, because the client does not get to choose which rules
            apply to it.
          */}
          <span className="field__label">Jurisdiction &amp; ruleset</span>
          <p className="field--readonly">
            Legal Metrology (Packaged Commodities) Rules, 2011
          </p>
          <p className="hint">
            {health?.complianceRules
              ? `${health.complianceRules.verified} verified and ${health.complianceRules.unverified} unverified rule(s) are loaded. Only a verified rule can report a package as non-compliant.`
              : 'The loaded rule counts are read from the backend health endpoint.'}
          </p>
        </div>
      </div>

      <div className="card__body card__body--divided">
        <div className="field field--actions">
          <button
            type="submit"
            className="button button--primary button--block"
            disabled={!canSubmit || isBusy}
          >
            {isBusy ? (
              <>
                <span className="spinner" aria-hidden="true" />
                {busyLabel}
              </>
            ) : (
              'Start analysis'
            )}
          </button>
          <button
            type="button"
            className="button button--block"
            onClick={onReset}
            disabled={isBusy}
          >
            Clear
          </button>
        </div>
        {!canSubmit && (
          <p className="hint">Requires product imagery to begin.</p>
        )}
      </div>
    </div>
  );
}
