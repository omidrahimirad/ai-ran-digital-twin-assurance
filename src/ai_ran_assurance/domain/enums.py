from enum import StrEnum


class AnomalyType(StrEnum):
    THRESHOLD = "threshold"
    STATISTICAL = "statistical"
    ML = "ml"


class RootCauseCategory(StrEnum):
    NORMAL = "normal"
    CONGESTION = "congestion"
    INTERFERENCE = "interference"
    NEIGHBOR_RELATION = "neighbor_relation"
    CELL_OUTAGE = "cell_outage"
    TRANSPORT = "transport"
    COVERAGE = "coverage"
    RADIO_QUALITY = "radio_quality"
    MOBILITY_CONFIGURATION = "mobility_configuration"
    UNKNOWN = "unknown"


class ActionType(StrEnum):
    RESTORE_NEIGHBOR = "restore_neighbor_relation"
    STEER_TRAFFIC = "steer_traffic"
    ROLLBACK_PARAMETER = "rollback_configuration_parameter"
    ACTIVATE_CAPACITY = "activate_additional_capacity"
    HUMAN_REVIEW = "no_action_human_review"


class FaultType(StrEnum):
    CELL_CONGESTION = "cell_congestion"
    INCREASED_INTERFERENCE = "increased_interference"
    MISSING_NEIGHBOR = "missing_neighbor_relation"
    CELL_OUTAGE = "cell_outage"
    TRANSPORT_LATENCY = "transport_latency_degradation"
    COVERAGE_DEGRADATION = "coverage_degradation"
    BLER_INCREASE = "abnormal_bler_increase"
    MOBILITY_MISCONFIGURATION = "mobility_parameter_misconfiguration"


class DecisionStatus(StrEnum):
    SHADOW_APPROVED = "shadow_approved"
    SHADOW_REJECTED = "shadow_rejected"
    HUMAN_REVIEW = "human_review_required"
