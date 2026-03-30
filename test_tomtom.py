"""Run this to check raw TomTom API responses."""
import asyncio
import httpx
from app.config import settings

LAT = 13.7563
LON = 100.5018

async def test_incidents():
    url = "https://api.tomtom.com/traffic/services/5/incidentDetails"
    params = {
        "key": settings.TOMTOM_API_KEY,
        "bbox": f"{LON-0.05},{LAT-0.05},{LON+0.05},{LAT+0.05}",
        "fields": "{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,events{description,code,iconCategory},startTime,endTime,from,to,length,delay,roadNumbers,timeValidity}}}",
        "language": "en-GB",
        "timeValidityFilter": "present"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=10)
        print("=== INCIDENTS ===")
        print("Status:", response.status_code)
        print("Response:", response.text[:1000])

async def test_flow():
    url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
    params = {
        "key": settings.TOMTOM_API_KEY,
        "point": f"{LAT},{LON}",
        "unit": "KMPH"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=10)
        print("\n=== FLOW ===")
        print("Status:", response.status_code)
        print("Response:", response.text[:1000])

async def main():
    print(f"Testing TomTom API for Bangkok ({LAT}, {LON})\n")
    await test_incidents()
    await test_flow()

asyncio.run(main())
