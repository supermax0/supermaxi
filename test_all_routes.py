import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

print("Testing more app routes as a logged-in tenant...")

try:
    from app import app
    app.testing = True
    client = app.test_client()
    
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['tenant_slug'] = 'alnoor'
        sess['role'] = 'admin'
        sess['name'] = 'Test Admin'
    
    routes_to_test = [
        '/inventory/',
        '/orders/',
        '/pos/',
        '/accounts/',
        '/suppliers/',
        '/customers/'
    ]
    
    for route in routes_to_test:
        print(f"\n--- Testing {route} ---")
        try:
            response = client.get(route, follow_redirects=True)
            print(f"  Status Code: {response.status_code}")
            if response.status_code == 500:
                print(f"  [!] ERROR 500 on {route}")
            elif response.status_code == 200:
                print(f"  Success! (200 OK)")
            else:
                print(f"  Status: {response.status_code}")
        except Exception as e:
            print(f"  [!!] CRITICAL EXCEPTION on {route}: {e}")
            import traceback
            traceback.print_exc()

except Exception as e:
    print(f"Could not initialize app for testing: {e}")
    import traceback
    traceback.print_exc()

print("\nTesting finished.")
