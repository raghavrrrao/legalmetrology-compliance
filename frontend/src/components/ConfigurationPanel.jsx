/**
 * Step two: what the photo shows, and what kind of product it is.
 *
 * Two controls survive from the original design's sidebar and one does not, and
 * the difference is whether the backend has the data behind it.
 *
 * - **Product category** is a text field, not a dropdown. It selects which
 *   rules apply, and the categories live in `ProductCategory` rows — but no
 *   endpoint lists them (`GET /api/v1/products/` is documented as planned). A
 *   dropdown would mean hardcoding backend rows into JavaScript, which drifts
 *   silently the moment a category is added or deactivated. The backend
 *   validates the code and rejects an unknown one with a message this screen
 *   renders, so a typo is caught where the answer actually is. A datalist
 *   offers no suggestions for the same reason.
 * - **Which part of the package** is a real `ProductImage.ViewType` the API
 *   accepts, and it genuinely changes how a result should be read. Its
 *   explanation is the most load-bearing sentence on this screen: a declaration
 *   that is not in the photograph has not been shown to be missing from the
 *   package, and a user who does not understand that will read an honest
 *   "requires review" as a failure.
 * - **Inspection scope** is gone. The design's "Mandatory Declarations Only"
 *   has no counterpart in the API — the request body has no scope, rule,
 *   check-type or severity parameter, deliberately.
 *
 * The jurisdiction is shown, not chosen. There is one ruleset and the client
 * must not be able to pick it: a verdict you can steer by choosing your own
 * rules is worth nothing. It sits under a disclosure because it is the same
 * answer on every check and it is not what a submitter is here to decide.
 *
 * The design's "Findings Requirements Preview" — a list of Product Name, Net
 * Quantity, MRP and so on — is deliberately not reproduced. Those are legal
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
  isBusy,
}) {
  return (
    <div className="card">
      <div className="card__header">
        <h2 className="card__title">Package details</h2>
      </div>

      <div className="card__body">
        <p className="lede-text">
          These details help us work out which requirements may apply.
        </p>

        <div className="field">
          <label htmlFor="scan-category">What kind of product is this?</label>
          <p className="hint" id="scan-category-help">
            Leave it blank if you are not sure — the result will say the product
            type was not known rather than assume one.
          </p>
          <input
            id="scan-category"
            type="text"
            value={categoryCode}
            placeholder="e.g. packaged-food"
            aria-describedby="scan-category-help"
            disabled={isBusy}
            onChange={(event) => onCategoryCodeChange(event.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="scan-view-type">
            Which part of the package does your photo show?
          </label>
          <p className="hint" id="scan-view-type-help">
            This matters because a declaration that is not visible in this photo
            cannot automatically be treated as missing from the package.
          </p>
          <select
            id="scan-view-type"
            value={viewType}
            aria-describedby="scan-view-type-help"
            disabled={isBusy}
            onChange={(event) => onViewTypeChange(event.target.value)}
          >
            {VIEW_TYPES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>

        <details className="technical-details">
          <summary>Which rules are being used?</summary>
          {/*
            Not a <label>: there is no control to label. This value is not
            selectable, because the client does not get to choose which rules
            apply to it.
          */}
          <p className="field--readonly">
            Legal Metrology (Packaged Commodities) Rules, 2011
          </p>
          <p className="hint">
            {health?.complianceRules
              ? `${health.complianceRules.verified} verified and ${health.complianceRules.unverified} unverified rule(s) are loaded. Only a verified rule can report a package as non-compliant.`
              : 'The loaded rule counts are read from the backend health endpoint.'}
          </p>
          <p className="hint">
            You cannot choose which rules apply. They are decided by the loaded
            rule set and the product type.
          </p>
        </details>
      </div>
    </div>
  );
}
