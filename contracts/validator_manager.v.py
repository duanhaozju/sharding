# NOTE: Some variables are set as public variables for testing. They should be reset
# to private variables in an official deployment of the contract. 
# NOTE: NOTARY_LOCKUP_LENGTH is set to 120 for testing. It should be set according
# to spec in an official deployment of the contract.

# Events
CollationAdded: __log__({
    shard_id: indexed(int128),
    expected_period_number: int128,
    period_start_prevhash: bytes32,
    parent_hash: bytes32,
    transaction_root: bytes32,
    collation_coinbase: address,
    state_root: bytes32,
    receipt_root: bytes32,
    collation_number: int128,
    is_new_head: bool,
    score: int128,
})
RegisterNotary: __log__({index_in_notary_pool: int128, notary: address})
DeregisterNotary: __log__({index_in_notary_pool: int128, notary: address, deregistered_period: int128})
ReleaseNotary: __log__({index_in_notary_pool: int128, notary: address})

# Notary pool
# - notary_pool: array of active notary addresses
# - notary_pool_len: size of the notary pool
# - empty_slots_stack: stack of empty notary slot indices
# - empty_slots_stack_top: top index of the stack
notary_pool: public(address[int128])
notary_pool_len: public(int128)
empty_slots_stack: public(int128[int128])
empty_slots_stack_top: public(int128)

# Notary registry
# - deregistered: the period when the notary deregister. It defaults to 0 for not yet deregistered notarys
# - pool_index: indicates notary's index in the notary pool
notary_registry: {
    deregistered: int128,
    pool_index: int128
}[address]
# - does_notary_exist: returns true if notary's record exist in notary registry
does_notary_exist: public(bool[address])

# Information about validators
validators: public({
    # Amount of wei the validator holds
    deposit: wei_value,
    # Address of the validator
    addr: address,
}[int128])

# Number of validators
num_validators: public(int128)

# Collation headers: (parent_hash || score)
# parent_hash: 26 bytes
# score: 6 bytes
collation_headers: public(bytes32[bytes32][int128])

# Receipt data
receipts: public({
    shard_id: int128,
    tx_startgas: int128,
    tx_gasprice: int128,
    value: wei_value,
    sender: address,
    to: address,
    data: bytes <= 4096,
}[int128])

# Current head of each shard
shard_head: public(bytes32[int128])

# Number of receipts
num_receipts: int128

# Log the latest period number of the shard
period_head: public(int128[int128])


# Configuration Parameter

# The total number of shards within a network.
# Provisionally SHARD_COUNT := 100 for the phase 1 testnet.
SHARD_COUNT: int128

# The period of time, denominated in main chain block times, during which
# a collation tree can be extended by one collation.
# Provisionally PERIOD_LENGTH := 5, approximately 75 seconds.
PERIOD_LENGTH: int128

# The lookahead time, denominated in periods, for eligible collators to
# perform windback and select proposals.
# Provisionally LOOKAHEAD_LENGTH := 4, approximately 5 minutes.
LOOKAHEAD_LENGTH: int128

# The fixed-size deposit, denominated in ETH, required for registration.
# Provisionally COLLATOR_DEPOSIT := 1000 and PROPOSER_DEPOSIT := 1.
NOTARY_DEPOSIT: wei_value

# The amount of time, denominated in periods, a deposit is locked up from the
# time of deregistration.
# Provisionally COLLATOR_LOCKUP_LENGTH := 16128, approximately two weeks, and
# PROPOSER_LOCKUP_LENGTH := 48, approximately one hour.
NOTARY_LOCKUP_LENGTH: int128


@public
def __init__(
        _SHARD_COUNT: int128,
        _PERIOD_LENGTH: int128,
        _LOOKAHEAD_LENGTH: int128,
        _NOTARY_DEPOSIT: wei_value,
        _NOTARY_LOCKUP_LENGTH: int128,
    ):
    self.SHARD_COUNT = _SHARD_COUNT
    self.PERIOD_LENGTH = _PERIOD_LENGTH
    self.LOOKAHEAD_LENGTH = _LOOKAHEAD_LENGTH
    self.NOTARY_DEPOSIT = _NOTARY_DEPOSIT
    self.NOTARY_LOCKUP_LENGTH = _NOTARY_LOCKUP_LENGTH


# Checks if empty_slots_stack_top is empty
@private
def is_empty_slots_stack_empty() -> bool:
    return (self.empty_slots_stack_top == 0)


# Pushes one int128 to empty_slots_stack
@private
def empty_slots_stack_push(index: int128):
    self.empty_slots_stack[self.empty_slots_stack_top] = index
    self.empty_slots_stack_top += 1


# Pops one int128 out of empty_slots_stack
@private
def empty_slots_stack_pop() -> int128:
    if self.is_empty_slots_stack_empty():
        return -1
    self.empty_slots_stack_top -= 1
    return self.empty_slots_stack[self.empty_slots_stack_top]


# Returns the current maximum index for validators mapping
@private
@constant
def get_validators_max_index() -> int128:
    activate_validator_num: int128 = 0
    all_validator_slots_num: int128 = self.num_validators + self.empty_slots_stack_top

    # TODO: any better way to iterate the mapping?
    for i in range(1024):
        if i >= all_validator_slots_num:
            break
        if not not self.validators[i].addr:
            activate_validator_num += 1
    return activate_validator_num + self.empty_slots_stack_top


# Helper functions to get notary info in notary_registry
@public
@constant
def get_notary_info(notary_address: address) -> (int128, int128):
    return (self.notary_registry[notary_address].deregistered, self.notary_registry[notary_address].pool_index)


# Adds an entry to notary_registry, updates the notary pool (notary_pool, notary_pool_len, etc.),
# locks a deposit of size NOTARY_DEPOSIT, and returns True on success.
@public
@payable
def register_notary() -> bool:
    assert msg.value >= self.NOTARY_DEPOSIT
    assert not self.does_notary_exist[msg.sender]
    
    # Add the notary to the notary pool
    pool_index: int128 = self.notary_pool_len
    if not self.is_empty_slots_stack_empty():
        pool_index = self.empty_slots_stack_pop()        
    self.notary_pool[pool_index] = msg.sender
    self.notary_pool_len += 1

    # Add the notary to the notary registry
    self.notary_registry[msg.sender] = {
        deregistered: 0,
        pool_index: pool_index,
    }
    self.does_notary_exist[msg.sender] = True

    log.RegisterNotary(pool_index, msg.sender)

    return True


# Sets the deregistered period in the notary_registry entry, updates the notary pool (notary_pool, notary_pool_len, etc.),
# and returns True on success.
@public
def deregister_notary() -> bool:
    assert self.does_notary_exist[msg.sender] == True

    # Delete entry in notary pool
    index_in_notary_pool: int128 = self.notary_registry[msg.sender].pool_index 
    self.empty_slots_stack_push(index_in_notary_pool)
    self.notary_pool[index_in_notary_pool] = None
    self.notary_pool_len -= 1

    # Set deregistered period to current period
    self.notary_registry[msg.sender].deregistered = floor(block.number / self.PERIOD_LENGTH)

    log.DeregisterNotary(index_in_notary_pool, msg.sender, self.notary_registry[msg.sender].deregistered)

    return True


# Removes an entry from notary_registry, releases the notary deposit, and returns True on success.
@public
def release_notary() -> bool:
    assert self.does_notary_exist[msg.sender] == True
    assert self.notary_registry[msg.sender].deregistered != 0
    assert floor(block.number / self.PERIOD_LENGTH) > self.notary_registry[msg.sender].deregistered + self.NOTARY_LOCKUP_LENGTH

    pool_index: int128 = self.notary_registry[msg.sender].pool_index
    # Delete entry in notary registry
    self.notary_registry[msg.sender] = {
        deregistered: 0,
        pool_index: 0,
    }
    self.does_notary_exist[msg.sender] = False

    send(msg.sender, self.NOTARY_DEPOSIT)

    log.ReleaseNotary(pool_index, msg.sender)

    return True


# Helper function to get collation header score
@public
@constant
def get_collation_header_score(shard_id: int128, collation_header_hash: bytes32) -> int128:
    collation_score: int128 = convert(
        uint256_mod(
            convert(self.collation_headers[shard_id][collation_header_hash], 'uint256'),
            # Mod 2^48, i.e., extract right most 6 bytes
            convert(281474976710656, 'uint256')
        ),
        'int128'
    )
    return collation_score


# Uses a block hash as a seed to pseudorandomly select a signer from the validator set.
# [TODO] Chance of being selected should be proportional to the validator's deposit.
# Should be able to return a value for the current period or any future period up to.
@public
@constant
def get_eligible_proposer(shard_id: int128, period: int128) -> address:
    assert period >= self.LOOKAHEAD_LENGTH
    assert (period - self.LOOKAHEAD_LENGTH) * self.PERIOD_LENGTH < block.number
    assert self.num_validators > 0
    return self.validators[
        convert(
            uint256_mod(
                convert(
                        sha3(
                            concat(
                                # TODO: should check further if this can be further optimized or not
                                #       e.g. be able to get the proposer of one period earlier
                                blockhash((period - self.LOOKAHEAD_LENGTH) * self.PERIOD_LENGTH),
                                convert(shard_id, 'bytes32'),
                            )
                        ),
                        'uint256'
                ),
                convert(self.get_validators_max_index(), 'uint256')
            ),
            'int128'
        )
    ].addr


# Attempts to process a collation header, returns True on success, reverts on failure.
@public
def add_header(
        shard_id: int128,
        expected_period_number: int128,
        period_start_prevhash: bytes32,
        parent_hash: bytes32,
        transaction_root: bytes32,
        collation_coinbase: address,  # TODO: cannot be named `coinbase` since it is reserved
        state_root: bytes32,
        receipt_root: bytes32,
        collation_number: int128) -> bool:  # TODO: cannot be named `number` since it is reserved

    # Check if the header is valid
    assert (shard_id >= 0) and (shard_id < self.SHARD_COUNT)
    assert block.number >= self.PERIOD_LENGTH
    assert expected_period_number == floor(block.number / self.PERIOD_LENGTH)
    assert period_start_prevhash == blockhash(expected_period_number * self.PERIOD_LENGTH - 1)
    # Check if only one collation in one period perd shard
    assert self.period_head[shard_id] < expected_period_number

    # Check if this header already exists
    header_bytes: bytes <= 288 = concat(
        convert(shard_id, 'bytes32'),
        convert(expected_period_number, 'bytes32'),
        period_start_prevhash,
        parent_hash,
        transaction_root,
        convert(collation_coinbase, 'bytes32'),
        state_root,
        receipt_root,
        convert(collation_number, 'bytes32'),
    )
    entire_header_hash: bytes32 = convert(
        uint256_mod(
            convert(sha3(header_bytes), 'uint256'),
            # Mod 2^208, i.e., extract right most 26 bytes
            convert(411376139330301510538742295639337626245683966408394965837152256, 'uint256')
        ),
        'bytes32'
    )
    
    # Check if parent header exists.
    # If it exist, check that it's score is greater than 0.
    parent_collation_score: int128 = self.get_collation_header_score(
        shard_id,
        parent_hash,
    )
    if not not parent_hash:
        assert parent_collation_score > 0

    # Check that there's eligible proposer in this period
    # and msg.sender is also the eligible proposer
    validator_addr: address = self.get_eligible_proposer(
        shard_id,
        floor(block.number / self.PERIOD_LENGTH)
    )
    assert not not validator_addr
    assert msg.sender == validator_addr

    # Check score == collation_number
    _score: int128 = parent_collation_score + 1
    assert collation_number == _score

    # Add the header
    self.collation_headers[shard_id][entire_header_hash] = convert(
        uint256_add(
            uint256_mul(
                convert(parent_hash, 'uint256'),
                # Multiplied by 2^48, i.e., left shift 6 bytes
                convert(281474976710656, 'uint256')
            ),
            uint256_mod(
                convert(_score, 'uint256'),
                # Mod 2^48, i.e. confine it's range to 6 bytes
                convert(281474976710656, 'uint256')
            ),
        ),
        'bytes32'
    )

    # Update the latest period number
    self.period_head[shard_id] = expected_period_number

    # Determine the head
    is_new_head: bool = False
    shard_head_score: int128 = self.get_collation_header_score(
        shard_id,
        self.shard_head[shard_id],
    )
    if _score > shard_head_score:
        self.shard_head[shard_id] = entire_header_hash
        is_new_head = True

    # Emit log
    log.CollationAdded(
        shard_id,
        expected_period_number,
        period_start_prevhash,
        parent_hash,
        transaction_root,
        collation_coinbase,
        state_root,
        receipt_root,
        collation_number,
        is_new_head,
        _score,
    )

    return True


# Returns the gas limit that collations can currently have (by default make
# this function always answer 10 million).
@public
@constant
def get_collation_gas_limit() -> int128:
    return 10000000


# Records a request to deposit msg.value ETH to address to in shard shard_id
# during a future collation. Saves a `receipt ID` for this request,
# also saving `msg.sender`, `msg.value`, `to`, `shard_id`, `startgas`,
# `gasprice`, and `data`.
@public
@payable
def tx_to_shard(
        to: address,
        shard_id: int128,
        tx_startgas: int128,
        tx_gasprice: int128,
        data: bytes <= 4096) -> int128:
    self.receipts[self.num_receipts] = {
        shard_id: shard_id,
        tx_startgas: tx_startgas,
        tx_gasprice: tx_gasprice,
        value: msg.value,
        sender: msg.sender,
        to: to,
        data: data,
    }
    receipt_id: int128 = self.num_receipts
    self.num_receipts += 1

    # TODO: determine the signature of the log TxToShard
    raw_log(
        [
            sha3("tx_to_shard(address,int128,int128,int128,bytes4096)"),
            convert(to, 'bytes32'),
            convert(shard_id, 'bytes32'),
        ],
        concat('', convert(receipt_id, 'bytes32')),
    )

    return receipt_id


# Updates the tx_gasprice in receipt receipt_id, and returns True on success.
@public
@payable
def update_gasprice(receipt_id: int128, tx_gasprice: int128) -> bool:
    assert self.receipts[receipt_id].sender == msg.sender
    self.receipts[receipt_id].tx_gasprice = tx_gasprice
    return True
