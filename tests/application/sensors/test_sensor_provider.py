from controlel.application.sensors.sensor_provider import SensorProvider


def test_sensor_provider_is_abstract():
    try:
        SensorProvider()
        assert False
    except TypeError:
        assert True
