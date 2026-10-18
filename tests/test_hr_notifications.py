from tests.test_hr_workspace import ctx,command,create_person,_client,_grant,JSON


def test_hr_alerts_expose_only_actionable_items_with_the_required_permission(ctx):
    admin=_client(ctx)
    person=create_person(admin,ctx)
    kind=command(admin,"leave_type.create",{"name":"سنوية","paid":True,"yearly_half_days":40}).get_json()["id"]
    assert command(admin,"leave.request",{"person_id":person,"type_id":kind,"starts":"2027-01-04","ends":"2027-01-04"}).status_code==200
    assert command(admin,"advance.request",{"person_id":person,"amount":100000,"instalments":2,"first_month":"2026-11","reason":"سلفة"}).status_code==200
    response=admin.get("/hr/api/notifications",headers=JSON)
    assert response.status_code==200,response.get_json()
    assert {i["type"] for i in response.get_json()["items"]} >= {"leave","advance"}
    _grant(ctx,"hr.view")
    clerk=_client(ctx,"clerk_id","cashier")
    assert clerk.get("/hr/api/notifications",headers=JSON).get_json()=={"items":[],"total":0}
    _grant(ctx,"hr.view","hr.leave.approve")
    items=clerk.get("/hr/api/notifications",headers=JSON).get_json()["items"]
    assert {i["type"] for i in items}=={"leave"}
    assert all("amount" not in i for i in items)
