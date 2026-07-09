package app.web;

import app.svc.OrderService;

public class OrderController {
    private final OrderService service = new OrderService();

    public String create() {
        return service.place();
    }

    public String status() {
        return service.lookup();
    }
}
