/*
 * Controlel — frontend i18n layer (vanilla JS, no build step).
 *
 * A small, dependency-free translation layer for the application shell:
 *   - stable translation keys (e.g. "navigation.overview"); translated text
 *     is presentation only and is never used as program logic or machine
 *     identity (module ids, reason codes, API status codes and
 *     frontend_api_version stay untranslated);
 *   - English is the canonical/fallback language;
 *   - supported languages: English (en) and Czech (cs);
 *   - the "auto" preference resolves the Home Assistant/frontend language
 *     when available and falls back to English for anything unsupported;
 *   - a missing key falls back to the English value, then to the key
 *     itself, so the UI can never render blank because of a missing
 *     translation;
 *   - the language preference is a frontend-local setting persisted in
 *     localStorage; no backend configuration or API endpoint is involved.
 *
 * The module is Node-safe so the behavior tests in tests/ can exercise it
 * without a browser.
 */
(function (global) {
  "use strict";

  const STORAGE_KEY = "controlel.ui.language";
  const SUPPORTED_LANGUAGES = ["en", "cs"];
  const PREFERENCES = ["auto", "en", "cs"];

  // ------------------------------------------------------------ catalogs
  //
  // English is canonical: every key exists here. Czech covers the current
  // user-facing shell; any key missing from Czech falls back to English.

  const MESSAGES = {
    en: {
      common: {
        unknown: "Unknown",
        none: "None",
        event: "event",
        loading: "Loading…",
        unavailable: "Unavailable",
        request_failed: "The request failed.",
        retry: "Retry",
        details: "Details",
        hide_details: "Hide details",
        issues: "Issues",
        no_issues: "No issues reported.",
      },
      navigation: {
        aria_label: "Main navigation",
        overview: "Overview",
        modules: "Modules",
        heating: "Heating",
        diagnostics: "Diagnostics",
        settings: "Settings",
        setup: "Setup",
      },
      state: {
        active: "Active",
        configured: "Configured",
        incomplete: "Incomplete",
        incomplete_setup: "Incomplete setup",
        attention: "Needs attention",
        disabled: "Disabled",
        not_configured: "Not configured",
        ok: "OK",
        idle: "Idle",
        unknown: "Unknown",
        inactive: "Inactive",
        error: "Error",
        degraded: "Degraded",
        stopped: "Stopped",
        ready: "Ready",
        invalid: "Invalid",
        heat_required: "Heating required",
        no_heat_required: "No heating demand",
        indeterminate: "Indeterminate",
        fresh: "Fresh",
        expired: "Expired",
        future_dated: "Future-dated",
        missing: "Missing",
      },
      mode: {
        demo: "Demo mode · mock data",
        real: "Frontend API v1 · live",
        disconnected: "Disconnected",
      },
      action: {
        continue_setup: "Continue setup",
        open_heating: "Open Heating",
        open_diagnostics: "Open Diagnostics",
        review_issues: "Review issues",
        enable_demo: "Enable demo mode (mock data)",
        show_debug: "Show Debug",
      },
      module: {
        no_reason: "No reason reported.",
        warnings: "{count} {warning}",
        no_warnings: "No warnings",
        updated: "Updated {time}",
      },
      activity: {
        reported_event: "Reported operational event (read-only).",
        reason_codes: "Reason codes",
        raw_metadata: "Raw metadata",
      },
      overview: {
        subtitle_api: "Frontend API v1",
        subtitle_generated: "Frontend API v1 · generated {time}",
        modules_lead: "Configured Controlel modules and their current state.",
        readonly_hint: "Read-only: actions only navigate; no backend writes are made.",
      },
      section: {
        modules: "Modules",
        issues: "Important warnings & issues",
        quick_actions: "Quick actions",
        all_modules: "All modules",
      },
      empty: {
        no_modules_title: "No modules reported",
        no_modules_message: "The backend reported no modules.",
        no_zones_title: "No zones reported",
        no_zones_message: "The backend reported no zones.",
        no_events_title: "No recent events",
        no_events_message: "Operational events will appear here.",
        no_events_level_title: "No events at this level",
        no_events_level_message: "Try a higher display level to see more detail.",
      },
      modules: {
        subtitle: "Each module is an independent capability.",
        note: "Only modules reported by the backend are shown. Modules that are not configured are not listed.",
      },
      heating: {
        subtitle: "Zone demand, heat source permission and reported state.",
        current_state: "Current state",
        current_lead: "Values are reports and assessments from the backend — not physical confirmation.",
        current_temperature: "Current temperature",
        measurement: "Measurement: {state}",
        target_temperature: "Target temperature",
        target_sub: "Comfort target for the zone",
        demand: "Heating demand",
        reason: "Reason: {code}",
        demand_sub: "Assessment from reported evidence",
        heat_source: "Heat source",
        permission: "Permission",
        requested_command: "Requested command",
        command_outcome: "Command outcome",
        reported_state: "Reported state",
        physical_state: "Physical state",
        physical_unknown: "Unknown (not reported)",
        distinct_note:
          "Permission, requested command, command outcome and reported state are distinct. None of them is physical " +
          "confirmation that the burner is running; the physical state is reported as unknown.",
        status_reason: "Status & reason",
        readiness_reason: "Readiness reason: {code}",
        no_readiness_reason: "No readiness reason reported.",
        completeness: "Configuration completeness",
        recent_events: "Recent operational events",
        readonly_note:
          "A successful command is not physical confirmation, and a heat source permission is not burner state. " +
          "Operational state remains read-only and separate from editable canonical configuration; this view performs no runtime control.",
      },
      canonical: {
        title: "Active Heating configuration",
        lead: "Canonical configuration v3 is the shared authority used by Heating, the Setup Wizard and Home Assistant Configure.",
        loading: "Loading the active canonical configuration…",
        load_failed: "Canonical configuration unavailable",
        unavailable: "Canonical editing is unavailable outside an authenticated Home Assistant connection.",
        single_zone_only: "This surface supports exactly one canonical Heating zone and one heat source.",
        active_revision: "Active revision",
        revision_number: "Revision number",
        generation: "Active generation",
        zone: "Zone",
        temperature_sensor: "Primary temperature sensor",
        heat_source_permission: "Heat source permission target",
        edit: "Edit configuration",
        reopen_draft: "Reopen draft",
        draft_available: "A compatible persisted draft exists. Edit will reopen it; the active revision remains unchanged.",
        draft_revision: "Draft revision {revision}",
        unsaved: "Unsaved changes",
        saved: "Draft saved",
        valid: "Validated",
        invalid: "Validation blocked",
        candidate_ready: "Canonical candidate ready",
        validation_issues: "Validation issues: {codes}",
        candidate_note: "Immutable candidate {revision} is ready for explicit activation.",
        save_draft: "Save Draft",
        validate: "Validate",
        canonicalize: "Canonicalize",
        activate: "Activate",
        working: "Canonical lifecycle operation in progress: {operation}",
        noneditable_note:
          "Stable Controlel identities, runtime/operational evidence, and deferred physical-operation fields are shown only through their projections and are not editable here.",
      },
      diagnostics: {
        title: "Diagnostics / Activity",
        subtitle: "Health, a readable activity list, and the latest decision trace.",
        health: "Health",
        runtime_status: "Runtime status",
        operating_mode: "Operating mode",
        events_emitted: "Events emitted",
        events_retained: "Events retained",
        events_dropped: "Events dropped",
        display_level: "Display level",
        display_level_lead: "Basic shows essential events; Detailed adds warnings; Debug adds critical detail.",
        level_basic: "Basic",
        level_detailed: "Detailed",
        level_debug: "Debug",
        activity: "Activity",
        decision_trace: "Latest decision trace",
        no_trace: "No decision trace reported.",
        decision: "Decision",
        zone: "Zone",
        sensor: "Sensor",
        action: "Action",
        observed_at: "Observed at",
        reason: "Reason",
        retained_total: "Retained / total",
      },
      settings: {
        subtitle: "Canonical-v3 setup lifecycle — runtime device control is not available here.",
        overview: "Settings overview",
        heating_config: "Heating configuration",
        heating_config_desc: "Zone, sensor and heat source bindings for the heating module.",
        diagnostics_level: "Diagnostics level",
        diagnostics_level_desc: "Basic, Detailed or Debug display level for the activity view.",
        notifications: "Notifications",
        notifications_desc: "Choose which Controlel events are surfaced (placeholder).",
        language: "Language",
        language_desc: "Interface language. The choice is stored in this browser only.",
        advanced: "Advanced",
        advanced_desc: "Advanced options and prototype diagnostics (placeholder).",
        placeholder: "Placeholder",
        note:
          "The Heating configuration row reflects the real setup readiness state. The setup wizard uses the " +
          "protected canonical-v3 lifecycle; other rows are placeholders.",
      },
      language: {
        auto: "Auto",
        en: "English",
        cs: "Czech",
      },
      setup: {
        title: "Setup / Readiness",
        subtitle: "Real setup readiness, missing configuration and validation from Frontend API v1.",
        readiness: "Readiness",
        ready: "Setup is reported as ready.",
        incomplete: "Setup is reported as incomplete. Resolve the items below before it can become active.",
        invalid: "Setup is reported as invalid. Review the validation messages below.",
        unknown: "Setup readiness is unknown.",
        missing_config: "Missing configuration",
        no_missing: "No missing configuration reported.",
        validation: "Validation messages",
        no_validation: "No validation messages reported.",
        readonly_note:
          "The wizard uses canonical configuration v3. Save, validation, canonicalization, and activation remain explicit separate actions.",
        heating: {
          unsupported_module_contract: "This draft uses an unsupported Heating setup contract.",
          invalid_setting: "The setting “{field}” is missing or invalid.",
          unsupported_binding_role: "The binding role “{role}” is not supported by this Heating setup.",
          required_binding_missing: "Select a {role}.",
          binding_confirmation_required: "Confirm the selected {role}.",
          simple_source_binding_mismatch: "The simple source-control enable and disable bindings must refer to the same target.",
          reported_source_binding_mismatch: "The reported source state must refer to the same target as simple source control.",
          discovery_snapshot_mismatch: "The validation snapshot does not match the requested discovery snapshot.",
          reference_resolver_unavailable: "The backend could not verify the selected Home Assistant references.",
          binding_missing: "The selected {role} no longer exists in the current Home Assistant discovery snapshot.",
          binding_recovery_requires_confirmation: "The selected {role} has a recovery candidate that requires confirmation.",
          binding_ambiguous: "The selected {role} is ambiguous in the current Home Assistant discovery snapshot.",
          binding_environment_mismatch: "The selected {role} belongs to a different Home Assistant environment.",
          binding_unsupported_resolution: "The backend could not resolve the selected {role}.",
          ephemeral_custom_service_target: "The custom service target for {role} has no stable registry identity.",
          ephemeral_important_binding: "The selected {role} has no stable registry identity.",
          binding_topology_changed: "The area or floor reported for {role} has changed since it was selected.",
          custom_service_target_capability_unverified: "The backend cannot verify the custom service capability for {role}.",
          binding_capability_unsuitable: "The selected {role} does not advertise the required capability.",
        },
      },
      setup_action: {
        confirm_external_service_target_stability: "Confirm that the external service target is stable.",
        select_registered_entity: "Select a registered Home Assistant entity.",
        review_binding_resolution: "Review and confirm the binding resolution.",
        review_current_area_and_floor: "Review the current area and floor.",
        verify_external_service_contract: "Verify the external service contract.",
        select_suitable_binding: "Select a binding with the required capability.",
      },
      unavailable: {
        subtitle: "Controlel is not connected to a Home Assistant Frontend API v1 source.",
        message:
          "No authenticated Home Assistant connection or Controlel config entry was found in this environment. " +
          "Real data is unavailable and will not be replaced by mock values.",
        note:
          "In a Home Assistant panel the shell uses the existing authenticated WebSocket connection and the " +
          "controlel/frontend_api/v1/* read-only commands. No custom authentication or transport is created here.",
      },
      panel: {
        tagline: "Heating control platform",
        readonly_footer: "Canonical v3 setup · explicit activation · no device control",
        overall_status: "Overall status",
        load_error: "Controlel panel failed to load",
        wizard_demo_label:
          "Prototype setup flow (demo data only) — real setup readiness is shown above. Activation is not implemented.",
        setup_steps: "Setup steps",
      },
      page: {
        title_app: "Controlel (Prototype)",
        title_wizard: "Controlel — Setup Wizard (Prototype)",
        wizard_header: "Controlel Setup",
        wizard_header_sub:
          "Heating module · Setup wizard prototype · Mock data only · No backend calls",
      },
      wizard: {
        step_discovery: "Discovery",
        step_zone: "Zone",
        step_sensor: "Sensor & Heat Source",
        step_settings: "Heating Settings",
        step_review: "Review & Validation",
        confidence: "Confidence: {level}",
        recommended: "Recommended",
        alternative: "Alternative",
        reasons: "Reasons:",
        confirm_binding:
          "I confirm using “{name}” as the {role}. " +
          "This is an important binding; a successful command is not physical confirmation.",
        role_zone: "Room / zone",
        role_sensor: "Primary temperature sensor",
        role_heat_source: "Heat source (enable/disable)",
        issue_zone_required: "Select a room/zone for this heating setup.",
        issue_sensor_required: "Select a primary temperature sensor.",
        issue_sensor_confirmation:
          "The primary temperature sensor is an important binding and requires explicit confirmation.",
        issue_heat_source_required: "Select a heat source (enable/disable).",
        issue_heat_source_confirmation:
          "The heat source is an important binding and requires explicit confirmation.",
        issue_area_mismatch:
          "Sensor area “{sensor}” differs from zone area “{zone}”. Verify this is intentional.",
        issue_ephemeral:
          "This heat source has no stable registry identity; rename recovery is not guaranteed.",
        not_saved: "Not saved yet",
        saved: "Saved {time}",
        in_memory: "in-memory prototype",
        complete: "Complete",
        incomplete: "Incomplete · {count} blocking",
        discovery_title: "Home Assistant discovery summary",
        discovery_lead:
          "A read-only snapshot of the Home Assistant installation. Discovery describes structure and advertised capability only.",
        snapshot: "Snapshot",
        provider: "Provider",
        instance: "Instance",
        snapshot_id: "Snapshot ID",
        captured_at: "Captured at",
        adapter_version: "Adapter version",
        fingerprint: "Fingerprint",
        count_floors: "Floors",
        count_areas: "Areas",
        count_devices: "Devices",
        count_entities: "Entities",
        refresh_snapshot: "Refresh snapshot (mock)",
        discovery_note:
          "Discovery is read-only and does not prove physical presence, measurement accuracy, or that a command will succeed. " +
          "No Controlel configuration was changed by this snapshot.",
        zone_title: "Select room / zone",
        zone_lead:
          "Choose the zone this heating setup controls. A Home Assistant area is not automatically a Controlel zone — this selection creates that mapping.",
        bindings_title: "Select temperature sensor and heat source",
        bindings_lead:
          "Both are important bindings. Each selection requires explicit confirmation; switching to a different candidate resets its confirmation.",
        sensor_lead:
          "The measurement the zone demand is based on. Command success is never treated as a physical reading.",
        heat_source_lead:
          "The source-control permission target. Enabling it grants heat source permission; it does not mean the burner is running.",
        simple_switch_lead:
          "Select one switch. Controlel derives its turn-on and turn-off bindings together; granting permission does not mean the burner is running.",
        settings_title: "Required heating settings",
        settings_lead: "Review the compact set of values required for a complete canonical Heating configuration.",
        settings_defaults_note: "These values start with the recommendations already used by the native Home Assistant setup and remain editable.",
        target_temperature: "Target temperature",
        measurement_max_age: "Maximum measurement age",
        maximum_future_skew: "Maximum future timestamp skew",
        indeterminate_grace: "Indeterminate grace period",
        seconds: "seconds",
        advanced_control_settings: "Advanced control timings",
        advanced_control_lead: "Canonical defaults are shown here; adjust them only when the heating system requires it.",
        turn_on_differential: "Turn-on differential",
        turn_off_differential: "Turn-off differential",
        demand_confirmation: "Demand confirmation",
        minimum_on_time: "Minimum heating-on time",
        minimum_off_time: "Minimum heating-off time",
        required_timing_settings: "Required timing settings",
        required_timing_summary: "Measurement age {age}s · future skew {skew}s · grace {grace}s",
        important_binding_note:
          "This is an important binding. Selecting a candidate is not confirmation — confirm it explicitly below the candidate.",
        not_selected: "Not selected",
        confirmed: "Confirmed",
        not_confirmed: "Not confirmed",
        activation: "Activation",
        activation_recorded: "Activation recorded",
        revision: "Revision",
        at: "At",
        activation_note:
          "Prototype only: no backend call was made and no active configuration was changed. " +
          "In the real lifecycle, activation applies one immutable canonical revision and keeps the previous revision for rollback.",
        readiness: "Readiness",
        ready_note: "All blocking items are resolved. This draft is ready to activate.",
        activate: "Activate",
        activate_hint: "Activating applies this draft as an immutable revision (mock).",
        fix_in_step: "Fix in step {step} · {label}",
        incomplete_note:
          "Setup is incomplete — {count} {blocking_item} must be resolved before this can become active. You can still save and finish later.",
        check_readiness: "Check readiness",
        cannot_activate: "An incomplete setup cannot become active.",
        draft_review: "Draft review",
        active_configuration: "Active configuration",
        current_draft: "Current draft",
        current_draft_validation: "Current draft validation",
        fix_blocking_issues: "Fix blocking issues",
        zone: "Zone",
        validation_report: "Validation report",
        validation_note:
          "Validation is evidence for this exact draft revision. Editing the draft creates a new revision and makes this report inapplicable.",
        validation_passed: "Validation passed — this draft is activation-ready.",
        warnings_recorded: "{count} {warning} recorded. Warnings do not block activation but should be reviewed.",
        review_title: "Review and validation",
        review_lead: "Check the draft, review the validation report, then save and finish later or activate.",
        back: "Back",
        save_later: "Save draft",
        delete_draft: "Delete draft / Start over",
        delete_draft_confirm: "Delete this persisted draft and start over? This cannot be undone.",
        continue: "Continue",
        not_discovered: "No discovery snapshot has been requested yet.",
        start_discovery: "Start discovery",
        discovering: "Discovering Home Assistant registry data…",
        discovery_unavailable: "Setup discovery unavailable",
        draft_unavailable: "Setup draft unavailable",
        start_new_draft: "Start a new draft",
        draft: "Draft",
        refresh_discovery: "Refresh discovery",
        no_areas: "No Home Assistant areas were discovered. The draft remains incomplete.",
        no_candidates: "No backend recommendation or candidate is available for this role.",
        no_candidates_in_area: "No compatible candidate was found in the selected room. Show more to review candidates from other rooms.",
        show_more_candidates: "Show more ({count})",
        show_fewer_candidates: "Show fewer",
        source_enable_target: "Heat source enable target",
        source_disable_target: "Heat source disable target",
        review_persisted_lead:
          "Review the canonical-v3 draft, then explicitly save, validate, canonicalize, and activate it.",
        unsaved_report: "Unsaved edits are not part of the backend validation report shown below.",
        blocking_count: "{count} blocking",
        warning_count: "{count} warnings",
        validation_preparation:
          "Validation prepares this draft only. No active configuration or runtime state is changed.",
        incomplete_draft: "Incomplete draft",
        draft_complete: "Draft complete",
        unsaved_edits: "unsaved edits",
        persisted: "persisted",
        saved_revision: "saved {time}",
        revision_status: "Revision {revision} · {status}",
        saving: "Saving…",
        validate_draft: "Validate draft",
        ready: "Ready",
        not_ready: "Not Ready",
        setup_entry: "Current backend setup state",
        entry_ready: "The backend reports setup as Ready. Ready does not mean a wizard draft was activated.",
        entry_incomplete: "The backend reports setup as incomplete. Continue in the wizard to create or resume a draft.",
        entry_invalid: "The backend reports setup as invalid. Continue in the wizard and review backend validation.",
        entry_unknown: "The backend setup state is unknown. The wizard will not assume that setup is ready.",
        entry_unavailable: "Backend setup readiness is unavailable: {message}",
        resume_available:
          "A saved draft reference ({draft}) is available in this browser. Resume will verify and load it from the backend.",
        resume_draft: "Resume draft",
        reported_source_state: "Reported heat source state",
        heat_delivery_actuator: "Heat delivery actuator",
        validation_issue_fallback: "Backend validation reported an issue. Review its code and technical details.",
        validation_path: "Field: {path}",
        ready_not_active: "Backend validation found no blocking issues for this saved draft. The draft is Ready, but it is not activated.",
        not_ready_not_saved: "This configuration has not been saved as a canonical-v3 draft yet.",
        not_ready_unsaved: "This draft has unsaved edits. Save and validate them before it can be Ready.",
        not_ready_validation: "Backend validation is {status}. Validate the saved draft to establish readiness.",
        not_ready_blocking: "Backend validation reports {count} blocking issue(s). The draft is not Ready.",
        validation_status_current: "Validation current",
        validation_status_stale: "Validation stale",
        validation_status_not_validated: "Not validated",
        blocking_issues: "Blocking issues",
        validation_warnings: "Warnings",
        no_blocking_issues: "No blocking issues were reported by backend validation.",
        complete_before_save: "Select and confirm a stable area, temperature sensor, and heat-source switch before the first canonical-v3 save.",
        canonical_v3_draft: "Canonical v3 draft",
        canonicalize: "Canonicalize",
        canonicalized_not_active: "Canonical revision {revision} was created. Active configuration is still unchanged.",
        activation_complete: "The canonical revision was activated through the protected backend lifecycle.",
      },
    },

    cs: {
      common: {
        unknown: "Neznámé",
        none: "Žádné",
        event: "událost",
        loading: "Načítání…",
        unavailable: "Nedostupné",
        request_failed: "Požadavek selhal.",
        retry: "Zkusit znovu",
        details: "Podrobnosti",
        hide_details: "Skrýt podrobnosti",
        issues: "Problémy",
        no_issues: "Nebyly hlášeny žádné problémy.",
      },
      navigation: {
        aria_label: "Hlavní navigace",
        overview: "Přehled",
        modules: "Moduly",
        heating: "Topení",
        diagnostics: "Diagnostika",
        settings: "Nastavení",
        setup: "Průvodce",
      },
      state: {
        active: "Aktivní",
        configured: "Nakonfigurováno",
        incomplete: "Nekompletní",
        incomplete_setup: "Nekompletní nastavení",
        attention: "Vyžaduje pozornost",
        disabled: "Vypnuto",
        not_configured: "Není nakonfigurováno",
        ok: "OK",
        idle: "Nečinné",
        unknown: "Neznámé",
        inactive: "Neaktivní",
        error: "Chyba",
        degraded: "Omezená funkčnost",
        stopped: "Zastaveno",
        ready: "Připraveno",
        invalid: "Neplatné",
        heat_required: "Vyžaduje topení",
        no_heat_required: "Žádná potřeba topení",
        indeterminate: "Nedostatečně určeno",
        fresh: "Aktuální",
        expired: "Expirované",
        future_dated: "S budoucím datem",
        missing: "Chybí",
      },
      mode: {
        demo: "Demo režim · ukázková data",
        real: "Frontend API v1 · živá data",
        disconnected: "Nepřipojeno",
      },
      action: {
        continue_setup: "Pokračovat v nastavení",
        open_heating: "Otevřít topení",
        open_diagnostics: "Otevřít diagnostiku",
        review_issues: "Zkontrolovat problémy",
        enable_demo: "Zapnout demo režim (ukázková data)",
        show_debug: "Zobrazit ladění",
      },
      module: {
        no_reason: "Nebyl hlášen žádný důvod.",
        warnings: "{count} {warning}",
        no_warnings: "Bez varování",
        updated: "Aktualizováno {time}",
      },
      activity: {
        reported_event: "Hlášená provozní událost (pouze pro čtení).",
        reason_codes: "Kódy důvodů",
        raw_metadata: "Surové metadata",
      },
      overview: {
        subtitle_api: "Frontend API v1",
        subtitle_generated: "Frontend API v1 · generováno {time}",
        modules_lead: "Nakonfigurované moduly Controlel a jejich aktuální stav.",
        readonly_hint: "Pouze pro čtení: akce pouze přepínají pohledy; do backendu se nic nezapisuje.",
      },
      section: {
        modules: "Moduly",
        issues: "Důležitá varování a problémy",
        quick_actions: "Rychlé akce",
        all_modules: "Všechny moduly",
      },
      empty: {
        no_modules_title: "Nebyly hlášeny žádné moduly",
        no_modules_message: "Backend neohlásil žádné moduly.",
        no_zones_title: "Nebyly hlášeny žádné zóny",
        no_zones_message: "Backend neohlásil žádné zóny.",
        no_events_title: "Žádné nedávné události",
        no_events_message: "Provozní události se zde zobrazí.",
        no_events_level_title: "Na této úrovni žádné události",
        no_events_level_message: "Zkuste vyšší úroveň zobrazení pro více podrobností.",
      },
      modules: {
        subtitle: "Každý modul je nezávislá funkčnost.",
        note: "Zobrazují se pouze moduly hlášené backendem. Nekonefigurované moduly se nezobrazují.",
      },
      heating: {
        subtitle: "Potřeba topení v zónách, oprávnění zdroje tepla a hlášený stav.",
        current_state: "Aktuální stav",
        current_lead: "Hodnoty jsou hlášení a posouzení z backendu — ne fyzikální potvrzení.",
        current_temperature: "Aktuální teplota",
        measurement: "Měření: {state}",
        target_temperature: "Cílová teplota",
        target_sub: "Cílová teplota pro komfort v zóně",
        demand: "Potřeba topení",
        reason: "Důvod: {code}",
        demand_sub: "Posouzení na základě hlášených údajů",
        heat_source: "Zdroj tepla",
        permission: "Oprávnění",
        requested_command: "Požadovaný příkaz",
        command_outcome: "Výsledek příkazu",
        reported_state: "Hlášený stav",
        physical_state: "Fyzikální stav",
        physical_unknown: "Neznámý (nehlášen)",
        distinct_note:
          "Oprávnění, požadovaný příkaz, výsledek příkazu a hlášený stav jsou odlišné pojmy. Žádné z nich není fyzikálním " +
          "potvrzením, že hořák běží; fyzikální stav je hlášen jako neznámý.",
        status_reason: "Stav a důvod",
        readiness_reason: "Důvod připravenosti: {code}",
        no_readiness_reason: "Nebyl hlášen žádný důvod připravenosti.",
        completeness: "Kompletnost konfigurace",
        recent_events: "Nedávné provozní události",
        readonly_note:
          "Úspěšný příkaz není fyzikálním potvrzením a oprávnění zdroje tepla není stavem hořáku. " +
          "Provozní stav zůstává jen pro čtení a oddělený od upravitelné kanonické konfigurace; tento pohled neprovádí řízení za běhu.",
      },
      canonical: {
        title: "Aktivní konfigurace topení",
        lead: "Kanonická konfigurace v3 je společnou autoritou pro Topení, Průvodce nastavením a konfiguraci v Home Assistant.",
        loading: "Načítání aktivní kanonické konfigurace…",
        load_failed: "Kanonická konfigurace není dostupná",
        unavailable: "Kanonické úpravy jsou dostupné pouze přes ověřené připojení Home Assistant.",
        single_zone_only: "Tato obrazovka podporuje právě jednu kanonickou zónu topení a jeden zdroj tepla.",
        active_revision: "Aktivní revize",
        revision_number: "Číslo revize",
        generation: "Aktivní generace",
        zone: "Zóna",
        temperature_sensor: "Primární teplotní senzor",
        heat_source_permission: "Cíl oprávnění zdroje tepla",
        edit: "Upravit konfiguraci",
        reopen_draft: "Znovu otevřít koncept",
        draft_available: "Existuje kompatibilní uložený koncept. Úprava jej znovu otevře; aktivní revize se nezmění.",
        draft_revision: "Revize konceptu {revision}",
        unsaved: "Neuložené změny",
        saved: "Koncept uložen",
        valid: "Ověřeno",
        invalid: "Ověření blokováno",
        candidate_ready: "Kanonický kandidát připraven",
        validation_issues: "Problémy ověření: {codes}",
        candidate_note: "Neměnný kandidát {revision} je připraven k výslovné aktivaci.",
        save_draft: "Uložit koncept",
        validate: "Ověřit",
        canonicalize: "Kanonizovat",
        activate: "Aktivovat",
        working: "Probíhá operace kanonického životního cyklu: {operation}",
        noneditable_note:
          "Stabilní identity Controlel, provozní údaje a odložená pole fyzického provozu se zde zobrazují pouze jako projekce a nelze je upravovat.",
      },
      diagnostics: {
        title: "Diagnostika / Aktivita",
        subtitle: "Zdraví systému, čitelný seznam aktivity a poslední stopa rozhodnutí.",
        health: "Zdraví",
        runtime_status: "Stav běhu",
        operating_mode: "Provozní režim",
        events_emitted: "Vydáno událostí",
        events_retained: "Uloženo událostí",
        events_dropped: "Zahozeno událostí",
        display_level: "Úroveň zobrazení",
        display_level_lead: "Základní zobrazuje podstatné události; Podrobné přidává varování; Ladění přidává kritické podrobnosti.",
        level_basic: "Základní",
        level_detailed: "Podrobné",
        level_debug: "Ladění",
        activity: "Aktivita",
        decision_trace: "Poslední stopa rozhodnutí",
        no_trace: "Nebyla hlášena žádná stopa rozhodnutí.",
        decision: "Rozhodnutí",
        zone: "Zóna",
        sensor: "Senzor",
        action: "Akce",
        observed_at: "Pozorováno",
        reason: "Důvod",
        retained_total: "Uloženo / celkem",
      },
      settings: {
        subtitle: "Životní cyklus nastavení canonical-v3 — přímé řízení zařízení zde není dostupné.",
        overview: "Přehled nastavení",
        heating_config: "Konfigurace topení",
        heating_config_desc: "Propojení zóny, senzoru a zdroje tepla pro modul topení.",
        diagnostics_level: "Úroveň diagnostiky",
        diagnostics_level_desc: "Úroveň zobrazení aktivity: Základní, Podrobné nebo Ladění.",
        notifications: "Oznámení",
        notifications_desc: "Vyberte, které události Controlel se zobrazují (rezervováno).",
        language: "Jazyk",
        language_desc: "Jazyk rozhraní. Volba se ukládá pouze v tomto prohlížeči.",
        advanced: "Pokročilé",
        advanced_desc: "Pokročilé možnosti a diagnostika prototypu (rezervováno).",
        placeholder: "Rezervováno",
        note:
          "Řádek Konfigurace topení odráží skutečný stav připravenosti. Průvodce používá chráněný životní " +
          "cyklus canonical-v3; ostatní řádky jsou rezervované.",
      },
      language: {
        auto: "Automaticky",
        en: "Angličtina",
        cs: "Čeština",
      },
      setup: {
        title: "Průvodce a připravenost",
        subtitle: "Skutečná připravenost, chybějící konfigurace a validace z Frontend API v1.",
        readiness: "Připravenost",
        ready: "Nastavení je hlášeno jako připravené.",
        incomplete: "Nastavení je hlášeno jako nekompletní. Před aktivací vyřešte položky níže.",
        invalid: "Nastavení je hlášeno jako neplatné. Zkontrolujte zprávy validace níže.",
        unknown: "Připravenost nastavení je neznámá.",
        missing_config: "Chybějící konfigurace",
        no_missing: "Nebyla hlášena žádná chybějící konfigurace.",
        validation: "Zprávy validace",
        no_validation: "Nebyly hlášeny žádné zprávy validace.",
        readonly_note:
          "Průvodce používá kanonickou konfiguraci v3. Uložení, validace, kanonizace a aktivace zůstávají samostatnými kroky.",
        heating: {
          unsupported_module_contract: "Tento koncept používá nepodporovaný kontrakt nastavení topení.",
          invalid_setting: "Nastavení „{field}“ chybí nebo je neplatné.",
          unsupported_binding_role: "Role propojení „{role}“ není tímto nastavením topení podporována.",
          required_binding_missing: "Vyberte {role}.",
          binding_confirmation_required: "Potvrďte vybrané propojení: {role}.",
          simple_source_binding_mismatch: "Propojení pro povolení a zakázání jednoduchého řízení zdroje musí odkazovat na stejný cíl.",
          reported_source_binding_mismatch: "Hlášený stav zdroje musí odkazovat na stejný cíl jako jednoduché řízení zdroje.",
          discovery_snapshot_mismatch: "Validační snímek neodpovídá požadovanému snímku objevu.",
          reference_resolver_unavailable: "Backend nemohl ověřit vybrané reference Home Assistant.",
          binding_missing: "Vybrané propojení {role} již v aktuálním snímku objevu Home Assistant neexistuje.",
          binding_recovery_requires_confirmation: "Vybrané propojení {role} má kandidáta na obnovení, který vyžaduje potvrzení.",
          binding_ambiguous: "Vybrané propojení {role} je v aktuálním snímku objevu Home Assistant nejednoznačné.",
          binding_environment_mismatch: "Vybrané propojení {role} patří do jiného prostředí Home Assistant.",
          binding_unsupported_resolution: "Backend nemohl vybrané propojení {role} vyřešit.",
          ephemeral_custom_service_target: "Cíl vlastní služby pro {role} nemá stabilní identitu v registru.",
          ephemeral_important_binding: "Vybrané propojení {role} nemá stabilní identitu v registru.",
          binding_topology_changed: "Oblast nebo podlaží hlášené pro {role} se od výběru změnily.",
          custom_service_target_capability_unverified: "Backend nemůže ověřit schopnost vlastní služby pro {role}.",
          binding_capability_unsuitable: "Vybrané propojení {role} nedeklaruje požadovanou schopnost.",
        },
      },
      setup_action: {
        confirm_external_service_target_stability: "Potvrďte stabilitu cíle externí služby.",
        select_registered_entity: "Vyberte entitu registrovanou v Home Assistant.",
        review_binding_resolution: "Zkontrolujte a potvrďte vyřešení propojení.",
        review_current_area_and_floor: "Zkontrolujte aktuální oblast a podlaží.",
        verify_external_service_contract: "Ověřte kontrakt externí služby.",
        select_suitable_binding: "Vyberte propojení s požadovanou schopností.",
      },
      unavailable: {
        subtitle: "Controlel není připojen ke zdroji Home Assistant Frontend API v1.",
        message:
          "V tomto prostředí nebylo nalezeno ověřené připojení k Home Assistant ani záznam konfigurace Controlel. " +
          "Skutečná data nejsou dostupná a nebudou nahrazena ukázkovými hodnotami.",
        note:
          "V panelu Home Assistant shell používá stávající ověřené WebSocket připojení a read-only příkazy " +
          "controlel/frontend_api/v1/*. Žádné vlastní ověřování ani transport se zde nevytváří.",
      },
      panel: {
        tagline: "Platforma pro řízení topení",
        readonly_footer: "Kanonické nastavení v3 · výslovná aktivace · bez ovládání zařízení",
        overall_status: "Celkový stav",
        load_error: "Panel Controlel se nepodařilo načíst",
        wizard_demo_label:
          "Prototypový průvodce nastavením (pouze ukázková data) — skutečná připravenost je uvedena výše. Aktivace není implementována.",
        setup_steps: "Kroky nastavení",
      },
      page: {
        title_app: "Controlel (prototyp)",
        title_wizard: "Controlel — Průvodce nastavením (prototyp)",
        wizard_header: "Nastavení Controlel",
        wizard_header_sub:
          "Modul topení · prototyp průvodce nastavením · pouze ukázková data · bez volání backendu",
      },
      wizard: {
        step_discovery: "Objev",
        step_zone: "Zóna",
        step_sensor: "Senzor a zdroj tepla",
        step_settings: "Nastavení topení",
        step_review: "Kontrola a validace",
        confidence: "Spolehlivost: {level}",
        recommended: "Doporučeno",
        alternative: "Alternativa",
        reasons: "Důvody:",
        confirm_binding:
          "Potvrzuji použití „{name}“ jako {role}. " +
          "Jedná se o důležité propojení; úspěšný příkaz není fyzikálním potvrzením.",
        role_zone: "Místnost / zóna",
        role_sensor: "Hlavní teplotní senzor",
        role_heat_source: "Zdroj tepla (zapnout/vypnout)",
        issue_zone_required: "Vyberte místnost/zónu pro toto nastavení topení.",
        issue_sensor_required: "Vyberte hlavní teplotní senzor.",
        issue_sensor_confirmation:
          "Hlavní teplotní senzor je důležité propojení a vyžaduje explicitní potvrzení.",
        issue_heat_source_required: "Vyberte zdroj tepla (zapnout/vypnout).",
        issue_heat_source_confirmation:
          "Zdroj tepla je důležité propojení a vyžaduje explicitní potvrzení.",
        issue_area_mismatch:
          "Oblast senzoru „{sensor}“ se liší od oblasti zóny „{zone}“. Ověřte, že je to záměrné.",
        issue_ephemeral:
          "Tento zdroj tepla nemá stabilní identitu v registru; obnova po přejmenování není zaručena.",
        not_saved: "Zatím neuloženo",
        saved: "Uloženo {time}",
        in_memory: "prototyp v paměti",
        complete: "Kompletní",
        incomplete: "Nekompletní · {count} blokujících",
        discovery_title: "Souhrn objevu v Home Assistant",
        discovery_lead:
          "Snímek instalace Home Assistant pouze pro čtení. Objev popisuje pouze strukturu a deklarované možnosti.",
        snapshot: "Snímek",
        provider: "Poskytovatel",
        instance: "Instance",
        snapshot_id: "ID snímku",
        captured_at: "Pořízeno",
        adapter_version: "Verze adaptéru",
        fingerprint: "Otisk",
        count_floors: "Podlaží",
        count_areas: "Oblasti",
        count_devices: "Zařízení",
        count_entities: "Entity",
        refresh_snapshot: "Obnovit snímek (simulace)",
        discovery_note:
          "Objev je pouze pro čtení a nedokládá fyzikální přítomnost, přesnost měření ani úspěch příkazu. " +
          "Tímto snímkem nebyla změněna žádná konfigurace Controlel.",
        zone_title: "Vyberte místnost / zónu",
        zone_lead:
          "Vyberte zónu, kterou toto nastavení topení řídí. Oblast Home Assistant není automaticky zónou Controlel — tímto výběrem se toto přiřazení vytváří.",
        bindings_title: "Vyberte teplotní senzor a zdroj tepla",
        bindings_lead:
          "Oba jsou důležitá propojení. Každý výběr vyžaduje explicitní potvrzení; přepnutí na jiného kandidáta potvrzení zruší.",
        sensor_lead:
          "Měření, na kterém se zakládá potřeba topení v zóně. Úspěch příkazu se nikdy nepovažuje za fyzikální měření.",
        heat_source_lead:
          "Cíl oprávnění zdroje tepla. Zapnutí uděluje oprávnění zdroje tepla; neznamená to, že hořák běží.",
        simple_switch_lead:
          "Vyberte jeden spínač. Controlel z něj společně odvodí vazby pro zapnutí i vypnutí; udělení oprávnění neznamená, že hořák běží.",
        settings_title: "Povinná nastavení topení",
        settings_lead: "Zkontrolujte kompaktní sadu hodnot vyžadovaných pro úplnou kanonickou konfiguraci topení.",
        settings_defaults_note: "Hodnoty začínají doporučeními používanými nativním nastavením Home Assistant a lze je upravit.",
        target_temperature: "Cílová teplota",
        measurement_max_age: "Maximální stáří měření",
        maximum_future_skew: "Maximální posun časového razítka do budoucnosti",
        indeterminate_grace: "Ochranná doba neurčitého stavu",
        seconds: "sekund",
        advanced_control_settings: "Pokročilé časování řízení",
        advanced_control_lead: "Zde jsou kanonické výchozí hodnoty; upravte je pouze podle potřeb topného systému.",
        turn_on_differential: "Diference zapnutí",
        turn_off_differential: "Diference vypnutí",
        demand_confirmation: "Potvrzení požadavku",
        minimum_on_time: "Minimální doba zapnutí topení",
        minimum_off_time: "Minimální doba vypnutí topení",
        required_timing_settings: "Povinná časová nastavení",
        required_timing_summary: "Stáří měření {age}s · budoucí posun {skew}s · ochranná doba {grace}s",
        important_binding_note:
          "Jedná se o důležité propojení. Výběr kandidáta není potvrzením — potvrďte jej explicitně pod kandidátem.",
        not_selected: "Nevybráno",
        confirmed: "Potvrzeno",
        not_confirmed: "Nepotvrzeno",
        activation: "Aktivace",
        activation_recorded: "Aktivace zaznamenána",
        revision: "Revize",
        at: "Kdy",
        activation_note:
          "Pouze prototyp: nebylo provedeno žádné volání backendu a nebyla změněna žádná aktivní konfigurace. " +
          "V reálném životním cyklu aktivace aplikuje jednu neměnnou kanonickou revizi a předchozí revizi ponechává pro návrat.",
        readiness: "Připravenost",
        ready_note: "Všechny blokující položky jsou vyřešeny. Tento koncept je připraven k aktivaci.",
        activate: "Aktivovat",
        activate_hint: "Aktivace aplikuje tento koncept jako neměnnou revizi (simulace).",
        fix_in_step: "Opravit ve kroku {step} · {label}",
        incomplete_note:
          "Nastavení je nekompletní — zbývá vyřešit {count} {blocking_item}. Stále jej můžete uložit a dokončit později.",
        check_readiness: "Zkontrolovat připravenost",
        cannot_activate: "Nekompletní nastavení nemůže být aktivní.",
        draft_review: "Kontrola konceptu",
        active_configuration: "Aktivní konfigurace",
        current_draft: "Aktuální koncept",
        current_draft_validation: "Validace aktuálního konceptu",
        fix_blocking_issues: "Opravit blokující problémy",
        zone: "Zóna",
        validation_report: "Zpráva o validaci",
        validation_note:
          "Validace je důkazem pro tento přesný koncept revize. Úprava konceptu vytvoří novou revizi a učiní tuto zprávu neplatnou.",
        validation_passed: "Validace proběhla — tento koncept je připraven k aktivaci.",
        warnings_recorded: "Zaznamenáno {count} {warning}. Varování aktivaci neblokují, ale je vhodné je zkontrolovat.",
        review_title: "Kontrola a validace",
        review_lead: "Zkontrolujte koncept, zprávu o validaci, poté uložte a dokončete později nebo aktivujte.",
        back: "Zpět",
        save_later: "Uložit koncept",
        delete_draft: "Smazat koncept / Začít znovu",
        delete_draft_confirm: "Smazat tento uložený koncept a začít znovu? Tuto akci nelze vrátit.",
        continue: "Pokračovat",
        not_discovered: "Zatím nebyl vyžádán žádný snímek objevu.",
        start_discovery: "Spustit objev",
        discovering: "Zjišťuji data registrů Home Assistant…",
        discovery_unavailable: "Objev nastavení není dostupný",
        draft_unavailable: "Koncept nastavení není dostupný",
        start_new_draft: "Založit nový koncept",
        draft: "Koncept",
        refresh_discovery: "Obnovit objev",
        no_areas: "Nebyly objeveny žádné oblasti Home Assistant. Koncept zůstává nekompletní.",
        no_candidates: "Pro tuto roli není dostupné doporučení ani kandidát z backendu.",
        no_candidates_in_area: "Ve vybrané místnosti nebyl nalezen kompatibilní kandidát. Další kandidáty z jiných místností zobrazíte pomocí „Zobrazit další“.",
        show_more_candidates: "Zobrazit další ({count})",
        show_fewer_candidates: "Zobrazit méně",
        source_enable_target: "Cíl povolení zdroje tepla",
        source_disable_target: "Cíl zakázání zdroje tepla",
        review_persisted_lead:
          "Zkontrolujte koncept canonical-v3 a poté jej samostatně uložte, validujte, kanonizujte a aktivujte.",
        unsaved_report: "Neuložené úpravy nejsou součástí níže zobrazeného validačního protokolu backendu.",
        blocking_count: "Blokující: {count}",
        warning_count: "Varování: {count}",
        validation_preparation:
          "Validace připravuje pouze tento koncept. Aktivní konfigurace ani stav běhu se nemění.",
        incomplete_draft: "Nekompletní koncept",
        draft_complete: "Koncept je kompletní",
        unsaved_edits: "neuložené úpravy",
        persisted: "uloženo",
        saved_revision: "uloženo {time}",
        revision_status: "Revize {revision} · {status}",
        saving: "Ukládání…",
        validate_draft: "Validovat koncept",
        ready: "Připraveno",
        not_ready: "Nepřipraveno",
        setup_entry: "Aktuální stav nastavení podle backendu",
        entry_ready: "Backend hlásí nastavení jako připravené. Připravenost neznamená, že byl koncept z průvodce aktivován.",
        entry_incomplete: "Backend hlásí nastavení jako nekompletní. V průvodci založte nový koncept nebo pokračujte v existujícím.",
        entry_invalid: "Backend hlásí nastavení jako neplatné. Pokračujte v průvodci a zkontrolujte validaci backendu.",
        entry_unknown: "Stav nastavení podle backendu je neznámý. Průvodce nebude předpokládat, že je nastavení připravené.",
        entry_unavailable: "Připravenost nastavení z backendu není dostupná: {message}",
        resume_available:
          "V tomto prohlížeči je uložen odkaz na koncept ({draft}). Pokračování jej ověří a načte z backendu.",
        resume_draft: "Pokračovat v konceptu",
        reported_source_state: "Hlášený stav zdroje tepla",
        heat_delivery_actuator: "Akční člen dodávky tepla",
        validation_issue_fallback: "Backend při validaci nahlásil problém. Zkontrolujte jeho kód a technické podrobnosti.",
        validation_path: "Pole: {path}",
        ready_not_active: "Validace backendu nenašla u tohoto uloženého konceptu žádné blokující problémy. Koncept je připravený, ale není aktivovaný.",
        not_ready_not_saved: "Tato konfigurace ještě nebyla uložena jako koncept canonical-v3.",
        not_ready_unsaved: "Koncept obsahuje neuložené úpravy. Před dosažením připravenosti je uložte a validujte.",
        not_ready_validation: "Stav validace backendu je {status}. Připravenost ověříte validací uloženého konceptu.",
        not_ready_blocking: "Validace backendu hlásí blokující problémy ({count}). Koncept není připravený.",
        validation_status_current: "Validace je aktuální",
        validation_status_stale: "Validace je zastaralá",
        validation_status_not_validated: "Nevalidováno",
        blocking_issues: "Blokující problémy",
        validation_warnings: "Varování",
        no_blocking_issues: "Validace backendu nenahlásila žádné blokující problémy.",
        complete_before_save: "Před prvním uložením canonical-v3 vyberte a potvrďte stabilní oblast, teplotní senzor a spínač zdroje tepla.",
        canonical_v3_draft: "Koncept canonical v3",
        canonicalize: "Kanonizovat",
        canonicalized_not_active: "Byla vytvořena kanonická revize {revision}. Aktivní konfigurace se zatím nezměnila.",
        activation_complete: "Kanonická revize byla aktivována přes chráněný životní cyklus backendu.",
      },
    },
  };

  // ------------------------------------------------------------- helpers

  /** Flatten a nested catalog into {"section.key": value} for O(1) lookup. */
  function flattenCatalog(nested, prefix, out) {
    for (const [key, value] of Object.entries(nested)) {
      const full = prefix ? prefix + "." + key : key;
      if (value && typeof value === "object") flattenCatalog(value, full, out);
      else out[full] = value;
    }
    return out;
  }

  // Flat lookup tables derived from the nested catalogs above.
  const CATALOGS = {
    en: flattenCatalog(MESSAGES.en, "", {}),
    cs: flattenCatalog(MESSAGES.cs, "", {}),
  };

  function baseLanguage(tag) {
    if (typeof tag !== "string") return null;
    const base = tag.toLowerCase().split(/[-_]/)[0];
    return base || null;
  }

  /**
   * Plural noun forms for `{noun}` placeholders, resolved from the `count`
   * param. The placeholder name is the semantic noun (e.g. {item},
   * {warning}, {blocking_item}); the active language picks the form.
   * Forms are keyed by CLDR plural category (one/few/many/other) and
   * selected with Intl.PluralRules, so adding a language means adding one
   * row per noun here. Components never branch on the language — they just
   * pass the count. A missing category falls back to "other", then English.
   */
  const PLURAL_NOUNS = {
    item: {
      en: { one: "item", other: "items" },
      cs: { one: "položka", few: "položky", many: "položek", other: "položek" },
    },
    warning: {
      en: { one: "warning", other: "warnings" },
      cs: { one: "varování", few: "varování", many: "varování", other: "varování" },
    },
    // Full noun phrase so the Czech adjective agrees with the noun
    // (1 blokující položka / 3 blokující položky / 5 blokujících položek).
    blocking_item: {
      en: { one: "blocking item", other: "blocking items" },
      cs: { one: "blokující položka", few: "blokující položky", many: "blokujících položek", other: "blokujících položek" },
    },
  };

  /**
   * Pick the plural form of a semantic noun for a count and language using
   * Intl.PluralRules. Falls back to the "other" form when the category is
   * missing or Intl.PluralRules is unavailable.
   */
  function pluralForm(noun, count, language) {
    const forms = PLURAL_NOUNS[noun];
    if (!forms) return String(noun);
    const langForms = forms[language] || forms.en;
    let category = "other";
    try {
      category = new Intl.PluralRules(language).select(count);
    } catch (_err) { category = "other"; }
    return langForms[category] !== undefined ? langForms[category] : langForms.other;
  }

  function isPreference(pref) {
    return PREFERENCES.includes(pref);
  }

  /**
   * Create an i18n instance.
   *
   * @param {object} [options]
   * @param {string} [options.preference]  "auto" | "en" | "cs"; when omitted,
   *                                      the stored preference is used.
   * @param {Function} [options.detect]    () => detected language tag (e.g. "cs-CZ")
   * @param {object}   [options.storage]   {getItem,setItem} for persistence
   * @param {Function} [options.onLanguageChange] (language) => side effects
   */
  function createI18n(options) {
    const opts = options || {};
    const storage = opts.storage || null;
    const detect = typeof opts.detect === "function" ? opts.detect : null;
    const notify = typeof opts.onLanguageChange === "function" ? opts.onLanguageChange : null;

    let preference;
    if (isPreference(opts.preference)) {
      preference = opts.preference;
    } else if (storage) {
      let stored = null;
      try { stored = storage.getItem(STORAGE_KEY); } catch (_err) { stored = null; }
      preference = isPreference(stored) ? stored : "auto";
    } else {
      preference = "auto";
    }

    function detectedLanguage() {
      if (!detect) return null;
      let tag = null;
      try { tag = detect(); } catch (_err) { tag = null; }
      return baseLanguage(tag);
    }

    function resolveLanguage() {
      if (preference === "en" || preference === "cs") return preference;
      const detected = detectedLanguage();
      return SUPPORTED_LANGUAGES.includes(detected) ? detected : "en";
    }

    function lookup(key) {
      const catalog = CATALOGS[language];
      if (catalog && Object.prototype.hasOwnProperty.call(catalog, key)) return catalog[key];
      if (language !== "en") {
        const en = CATALOGS.en;
        if (en && Object.prototype.hasOwnProperty.call(en, key)) return en[key];
      }
      return null;
    }

    let language = resolveLanguage();
    if (notify) { try { notify(language); } catch (_err) { /* side effect must not break i18n */ } }

    return {
      get preference() { return preference; },
      get language() { return language; },

      /** True when the key resolves in the active language or the English fallback. */
      has(key) { return lookup(key) !== null; },

      /**
       * Translate a key. Falls back to the English value, then to the key
       * itself, so the UI never renders blank. `params` substitutes
       * `{name}` placeholders.
       */
      t(key, params) {
        const value = lookup(key);
        if (value === null) return String(key);
        let out = value;
        if (params) {
          const p = Object.assign({}, params);
          if (p.count !== undefined) {
            for (const noun of Object.keys(PLURAL_NOUNS)) {
              if (p[noun] === undefined && out.indexOf("{" + noun + "}") !== -1) {
                p[noun] = pluralForm(noun, Number(p.count), language);
              }
            }
          }
          for (const [name, replacement] of Object.entries(p)) {
            out = out.split("{" + name + "}").join(String(replacement));
          }
        }
        return out;
      },

      /**
       * Set the language preference ("auto" | "en" | "cs"), persist it when
       * storage is available, and re-resolve the active language.
       */
      setLanguage(pref) {
        preference = isPreference(pref) ? pref : "auto";
        if (storage) {
          try { storage.setItem(STORAGE_KEY, preference); } catch (_err) { /* storage unavailable */ }
        }
        language = resolveLanguage();
        if (notify) { try { notify(language); } catch (_err) { /* side effect must not break i18n */ } }
        return language;
      },
    };
  }

  // ------------------------------------------------------- default instance

  let _default = null;

  /**
   * The shared instance used by the shell (app.js, components.js, wizard.js,
   * ha-panel.js). In a browser it detects the Home Assistant/frontend
   * language and persists the preference in localStorage; in Node it
   * resolves to English with no side effects.
   */
  function defaultI18n() {
    if (_default) return _default;

    const win = typeof window !== "undefined" ? window : null;
    let storage = null;
    try {
      if (win && win.localStorage) storage = win.localStorage;
      else if (typeof localStorage !== "undefined") storage = localStorage;
    } catch (_err) { storage = null; }

    const doc = win && win.document;
    _default = createI18n({
      storage,
      detect: () => {
        const hass = win && win.hass;
        if (hass && typeof hass.language === "string") return hass.language;
        const nav = win && win.navigator;
        if (nav && typeof nav.language === "string") return nav.language;
        return "en";
      },
      onLanguageChange: (lang) => {
        if (doc && doc.documentElement) doc.documentElement.lang = lang;
      },
    });
    return _default;
  }

  /**
   * Translate static markup: every element with a `data-i18n` attribute
   * receives the translated text for that key.
   */
  function applyI18n(root) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    const i18n = defaultI18n();
    for (const node of root.querySelectorAll("[data-i18n]")) {
      const key = node.getAttribute && node.getAttribute("data-i18n");
      if (key) node.textContent = i18n.t(key);
    }
  }

  global.CI18N = {
    STORAGE_KEY,
    SUPPORTED_LANGUAGES,
    PREFERENCES,
    MESSAGES,
    CATALOGS,
    createI18n,
    defaultI18n,
    applyI18n,
    get preference() { return defaultI18n().preference; },
    get language() { return defaultI18n().language; },
    has: (key) => defaultI18n().has(key),
    t: (key, params) => defaultI18n().t(key, params),
    setLanguage: (pref) => defaultI18n().setLanguage(pref),
  };
})(typeof window !== "undefined" ? window : globalThis);
