package app.svc;

import app.data.OrderRepo;

public class OrderService {
    private final OrderRepo repo = new OrderRepo();

    public String place() {
        validate();
        return repo.save();
    }

    public String lookup() {
        return repo.find();
    }

    private void validate() {
        // no-op
    }
}
