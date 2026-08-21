"""Production-neutral assembly contract for the ordinary control runtime."""

from dataclasses import dataclass, field
from datetime import timedelta

from controlel.application.ports.heat_source_port import HeatSourcePort
from controlel.application.ports.scheduled_runtime_failure_sink import ScheduledRuntimeFailureSink
from controlel.application.ports.scheduler import Scheduler
from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.services.demand_arbitrator import DemandArbitrator
from controlel.application.services.operating_mode_policy import DEFAULT_MANUAL_RECOVERY_DURATION
from controlel.application.services.operational_event_recorder import OperationalEventRecorder
from controlel.application.services.source_reconciliation_policy import (
    DEFAULT_CORRECTION_RETRY_INTERVAL,
    DEFAULT_UNKNOWN_TRANSITION_HOLD,
)
from controlel.application.services.source_recovery_policy import DEFAULT_RECOVERY_WINDOW
from controlel.application.services.zone_heat_delivery_controller import ZoneHeatDeliveryController
from controlel.application.state.runtime_supervision_state import RuntimeHandoverEvidence
from controlel.application.time.clock import Clock
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.operating_mode import SafeHeatingProfile
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.source_control import SourceCapabilities, SourceOwnership


@dataclass(frozen=True, slots=True)
class ControlRuntimeAssembly:
    """Hold adapter-neutral dependencies and construct one ordinary runtime."""

    sensor_repository: SensorRepository
    zone_repository: ZoneRepository
    clock: Clock
    scheduler: Scheduler
    scheduled_failure_sink: ScheduledRuntimeFailureSink
    max_future_skew: timedelta
    indeterminate_grace_period: timedelta
    indeterminate_timeout_action: HeatingAction
    heating_turn_on_differential: float = 0.0
    heating_turn_off_differential: float = 0.0
    heat_demand_confirmation_duration: timedelta = timedelta(0)
    minimum_heating_on_time: timedelta = timedelta(0)
    minimum_heating_off_time: timedelta = timedelta(0)
    demand_arbitrator: DemandArbitrator | None = None
    heat_delivery_controller: ZoneHeatDeliveryController | None = None
    source_ownership: SourceOwnership = SourceOwnership.EXTERNAL
    source_capabilities: SourceCapabilities = field(default_factory=SourceCapabilities)
    source_reconciliation_hold: timedelta = DEFAULT_UNKNOWN_TRANSITION_HOLD
    source_correction_retry_interval: timedelta = DEFAULT_CORRECTION_RETRY_INTERVAL
    source_recovery_window: timedelta = DEFAULT_RECOVERY_WINDOW
    safe_heating_profile: SafeHeatingProfile | None = None
    manual_recovery_duration: timedelta = DEFAULT_MANUAL_RECOVERY_DURATION
    operational_event_recorder: OperationalEventRecorder | None = None

    def build(
        self,
        heat_source_port: HeatSourcePort,
        *,
        handover: RuntimeHandoverEvidence | None = None,
    ) -> ControlRuntime:
        """Build through one shared constructor path and apply explicit handover evidence."""

        runtime = ControlRuntime(
            sensor_repository=self.sensor_repository,
            zone_repository=self.zone_repository,
            heat_source_port=heat_source_port,
            clock=self.clock,
            scheduler=self.scheduler,
            scheduled_failure_sink=self.scheduled_failure_sink,
            max_future_skew=self.max_future_skew,
            indeterminate_grace_period=self.indeterminate_grace_period,
            indeterminate_timeout_action=self.indeterminate_timeout_action,
            heating_turn_on_differential=self.heating_turn_on_differential,
            heating_turn_off_differential=self.heating_turn_off_differential,
            heat_demand_confirmation_duration=self.heat_demand_confirmation_duration,
            minimum_heating_on_time=self.minimum_heating_on_time,
            minimum_heating_off_time=self.minimum_heating_off_time,
            demand_arbitrator=self.demand_arbitrator,
            heat_delivery_controller=self.heat_delivery_controller,
            source_ownership=self.source_ownership,
            source_capabilities=self.source_capabilities,
            source_reconciliation_hold=self.source_reconciliation_hold,
            source_correction_retry_interval=self.source_correction_retry_interval,
            source_recovery_window=self.source_recovery_window,
            safe_heating_profile=self.safe_heating_profile,
            manual_recovery_duration=self.manual_recovery_duration,
            operational_event_recorder=self.operational_event_recorder,
        )
        if handover is not None:
            runtime.reported_source_evidence = handover.reported_source
            runtime.source_control_state = handover.source_control_state
            runtime.source_reconciliation_state = handover.reconciliation_state
        return runtime
